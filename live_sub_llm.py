import time
import os
import numpy as np
import logging
import pyaudiowpatch as pyaudio
from scipy import signal
from faster_whisper import WhisperModel
from PyQt5.QtCore import QThread, pyqtSignal
from openai import OpenAI

# ================= 配置区域 =================

# 1. 本地大模型设置 (连接 Ollama 或 LM Studio)
# 如果是 LM Studio，通常是 "http://localhost:1234/v1"
# 如果是 Ollama，通常是 "http://localhost:11434/v1"
# 设置不走代理
os.environ["NO_PROXY"] = "localhost,127.0.0.1,0.0.0.0"
os.environ["no_proxy"] = "localhost,127.0.0.1,0.0.0.0"
LLM_BASE_URL = "http://localhost:1234/v1"
LLM_API_KEY = "lm-studio"  # 本地模型通常随便填
# 您的模型名称 (在 LM Studio/Ollama 里查看，例如 "qwen2.5-14b-instruct")
LLM_MODEL_NAME = "local-model"

# 2. Whisper 设置
WHISPER_SIZE = "large-v3"  # 既然有LLM做后处理，Whisper可以用medium提速
DEVICE = "cuda"
BUFFER_DURATION = 2.0  # 稍微延长切片时间到 2秒
OVERLAP_DURATION = 0.5 # ★新增：每次多听前 0.5秒 的声音，防止切词


# ===========================================

class AudioWorker(QThread):
    text_updated = pyqtSignal(str)
    status_updated = pyqtSignal(str)

    def run(self):
        logging.info(f"正在加载 Whisper 模型: {WHISPER_SIZE}")
        self.status_updated.emit(f"正在加载 Whisper ({WHISPER_SIZE})...")

        try:
            whisper = WhisperModel(WHISPER_SIZE, device=DEVICE, compute_type="float16")
            logging.info("Whisper 模型加载成功")
        except Exception as e:
            logging.error(f"Whisper 加载失败: {e}", exc_info=True)
            self.status_updated.emit("模型加载失败，请检查日志")
            return

        # 连接 LLM
        client = None
        try:
            client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
            # 简单测试连接
            client.models.list()
            logging.info("本地 LLM 连接成功")
        except Exception as e:
            logging.warning(f"LLM 连接失败: {e}")
            self.status_updated.emit("⚠️ 本地 LLM 未连接")

        p = pyaudio.PyAudio()

        # 缓存上一段音频的尾巴，用于拼接
        prev_audio_chunk = np.array([], dtype=np.float32)

        while True:
            try:
                # --- 自动寻找 Loopback 设备 ---
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_device_index = wasapi_info["defaultOutputDevice"]
                device_info = p.get_device_info_by_index(default_device_index)

                if not device_info["isLoopbackDevice"]:
                    for loopback in p.get_loopback_device_info_generator():
                        if device_info["name"] in loopback["name"]:
                            device_info = loopback
                            break

                current_device_name = device_info['name']
                logging.info(f"绑定设备: {current_device_name}")
                self.status_updated.emit(f"监听: {current_device_name}")

                sys_rate = int(device_info["defaultSampleRate"])
                channels = device_info["maxInputChannels"]
                target_rate = 16000

                stream = p.open(format=pyaudio.paInt16,
                                channels=channels,
                                rate=sys_rate,
                                input=True,
                                input_device_index=device_info["index"],
                                frames_per_buffer=1024)

                frames = []
                frames_needed = int(sys_rate * BUFFER_DURATION / 1024)

                logging.info("音频流启动...")

                while True:
                    try:
                        data = stream.read(1024, exception_on_overflow=False)
                        frames.append(data)
                    except Exception:
                        break  # 设备可能断开，触发外层循环重连

                    if len(frames) >= frames_needed:
                        audio_bytes = b''.join(frames)
                        frames = []

                        # 1. 预处理
                        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                        audio_float = audio_np.astype(np.float32) / 32768.0

                        if channels > 1:
                            audio_float = audio_float.reshape(-1, channels).mean(axis=1)

                        if sys_rate != target_rate:
                            num_samples = int(len(audio_float) * target_rate / sys_rate)
                            audio_float = signal.resample(audio_float, num_samples)
                            audio_float = np.clip(audio_float, -1.0, 1.0)

                        # 2. 自动增益 (Auto Gain)
                        max_vol = np.max(np.abs(audio_float))
                        if max_vol < 0.01:
                            continue
                        elif max_vol < 0.5:
                            gain = 0.8 / (max_vol + 1e-6)
                            audio_float = audio_float * gain
                            audio_float = np.clip(audio_float, -1.0, 1.0)

                        # 3. 重叠拼接 (Overlap)
                        if len(prev_audio_chunk) > 0:
                            combined_audio = np.concatenate((prev_audio_chunk, audio_float))
                        else:
                            combined_audio = audio_float

                        overlap_samples = int(target_rate * OVERLAP_DURATION)
                        prev_audio_chunk = audio_float[-overlap_samples:]

                        # 4. Whisper 识别
                        segments, _ = whisper.transcribe(
                            combined_audio,
                            beam_size=5,
                            vad_filter=True,
                            vad_parameters=dict(min_silence_duration_ms=300),
                            condition_on_previous_text=False,
                            initial_prompt="以下是字幕，请忽略不完整句子。"
                        )

                        raw_text = " ".join([s.text for s in segments]).strip()

                        if len(raw_text) < 2: continue

                        logging.info(f"[原文] {raw_text}")

                        # 5. LLM 翻译
                        final_text = raw_text
                        if client:
                            try:
                                completion = client.chat.completions.create(
                                    model=LLM_MODEL_NAME,
                                    messages=[
                                        {"role": "system", "content": "翻译成中文。简练。"},
                                        {"role": "user", "content": raw_text}
                                    ],
                                    temperature=0.1, max_tokens=60
                                )
                                trans_text = completion.choices[0].message.content.strip()
                                logging.info(f"[译文] {trans_text}")
                                final_text = trans_text
                            except Exception as e:
                                logging.error(f"LLM 错误: {e}")

                        # 发送信号给 UI
                        self.text_updated.emit(final_text)

                stream.stop_stream()
                stream.close()
                time.sleep(1)

            except Exception as e:
                logging.error(f"Logic Error: {e}", exc_info=True)
                time.sleep(2)
