import os
import configparser
import logging

# ================= 1. 读取配置文件 (类似 Properties) =================
# 在加载其他重型库之前，先读取配置并设置环境变量
config = configparser.ConfigParser()

# 尝试读取 config.ini，如果不存在则使用默认值
if os.path.exists("config/config.ini"):
    config.read("config/config.ini", encoding="utf-8")
else:
    # 没找到文件时的硬编码默认值 (Fail-safe)
    logging.warning("⚠️ 未找到 config.ini，将使用默认配置！")
    config["Network"] = {"no_proxy": "localhost,127.0.0.1,0.0.0.0"}
    config["Whisper"] = {"model_size": "medium", "device": "cuda", "compute_type": "float16"}
    config["Audio"] = {"buffer_duration": "3.0", "sample_rate": "16000", "min_silence_ms": "500"}
    config["LLM"] = {"base_url": "http://localhost:1234/v1", "api_key": "lm-studio", "model_name": "local-model"}

# ================= 2. 设置环境变量 (关键！) =================
# 必须在 requests/openai 初始化前设置，否则可能无效
no_proxy_val = config.get("Network", "no_proxy", fallback="localhost,127.0.0.1,0.0.0.0")
os.environ["NO_PROXY"] = no_proxy_val
os.environ["no_proxy"] = no_proxy_val
logging.info(f"环境变量 NO_PROXY 已设置为: {no_proxy_val}")

# ================= 3. 导入其他依赖 =================
import time
import numpy as np
import queue
import threading
import pyaudiowpatch as pyaudio
from scipy import signal
from faster_whisper import WhisperModel
from openai import OpenAI
from PyQt5.QtCore import QThread, pyqtSignal

# 从配置中获取常量
WHISPER_SIZE = config.get("Whisper", "model_size")
DEVICE = config.get("Whisper", "device")
COMPUTE_TYPE = config.get("Whisper", "compute_type")
BUFFER_DURATION = config.getfloat("Audio", "buffer_duration")
SAMPLE_RATE = config.getint("Audio", "sample_rate")
MIN_SILENCE_MS = config.getint("Audio", "min_silence_ms")

LLM_BASE_URL = config.get("LLM", "base_url")
LLM_API_KEY = config.get("LLM", "api_key")
LLM_MODEL_NAME = config.get("LLM", "model_name")


class AudioWorker(QThread):
    text_updated = pyqtSignal(str, str)
    status_updated = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True
        self.audio_queue = queue.Queue(maxsize=10)
        self.history_context = []

    def run(self):
        # 1. 初始化 Whisper
        self.status_updated.emit(f"Loading {WHISPER_SIZE}...")
        try:
            logging.info(f"正在加载 Whisper: {WHISPER_SIZE} ({DEVICE})")
            whisper = WhisperModel(WHISPER_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
            logging.info("Whisper Loaded.")
        except Exception as e:
            logging.error(f"Whisper Init Failed: {e}", exc_info=True)
            self.status_updated.emit("Whisper 加载失败")
            return

        # 2. 初始化 LLM Client
        client = None
        try:
            client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
            # 测试连接
            client.models.list()
            logging.info(f"LLM Connected: {LLM_BASE_URL}")
        except Exception as e:
            logging.warning(f"LLM Connection Failed: {e}")
            self.status_updated.emit("⚠️ LLM 未连接 (仅显示原文)")

        # 3. 启动录音线程
        capture_thread = threading.Thread(target=self.capture_audio_loop, daemon=True)
        capture_thread.start()

        logging.info("Inference Loop Started.")

        # 4. 推理循环
        while self.running:
            try:
                audio_data_dict = self.audio_queue.get(timeout=1)
                audio_float = audio_data_dict['data']
            except queue.Empty:
                continue

            # --- A. Whisper 识别 ---
            try:
                segments, _ = whisper.transcribe(
                    audio_float,
                    beam_size=5,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=MIN_SILENCE_MS),
                    condition_on_previous_text=False
                )
                raw_text = " ".join([s.text for s in segments]).strip()
            except Exception as e:
                logging.error(f"Transcribe Error: {e}")
                continue

            if len(raw_text) < 2: continue

            # --- B. LLM 翻译 ---
            final_text = raw_text
            if client:
                try:
                    # 1. 构建上下文 (取最近 3 句，提供更多背景)
                    context_list = self.history_context[-3:]
                    context_str = " | ".join(context_list) if context_list else "无"

                    # 2. 定义系统提示词 (System Prompt)
                    # 这是提升效果的关键！
                    system_prompt = f"""
                    你是一位精通中英日多语言的【资深字幕翻译专家】。
                    你的任务是将输入的语音识别（ASR）文本翻译成**地道、简洁、流畅的中文**。

                    【翻译规则】：
                    1. **口语化**：翻译要符合中文日常说话习惯，拒绝生硬的“翻译腔”。
                    2. **意译优先**：结合上下文理解真实含义，不要逐字直译。例如 "It works" 翻译为 "这就行了" 而不是 "它工作"。
                    3. **ASR纠错**：输入文本可能包含语音识别错误、语气词或断句错误，请自动修正逻辑，忽略无意义的 "um", "ah" 等填充词。
                    4. **极简输出**：只输出翻译后的文本，**严禁**包含 "好的"、"翻译如下"、"Sure" 等任何解释性文字。
                    5. **特殊情况**：如果输入是无意义的噪音或乱码，直接输出 "..."。

                    【上下文参考】：
                    {context_str}
                    """

                    # 3. 发送请求
                    completion = client.chat.completions.create(
                        model=LLM_MODEL_NAME,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": raw_text}
                        ],
                        # 温度稍微调高一点点，让用词更灵活，但不要太高防止胡编
                        temperature=0.2,
                        max_tokens=100
                    )

                    # 4. 获取结果
                    translated_content = completion.choices[0].message.content.strip()

                    # 二次清洗：防止模型有时候还是会吐出 "翻译：" 开头的字样
                    translated_content = translated_content.replace("翻译：", "").replace("译文：", "")

                    final_text = translated_content

                    # 更新历史上下文
                    self.history_context.append(final_text)
                    if len(self.history_context) > 10:
                        self.history_context.pop(0)

                except Exception as e:
                    logging.error(f"LLM Error: {e}")

            self.text_updated.emit(raw_text, final_text)

    def capture_audio_loop(self):
        p = pyaudio.PyAudio()

        while self.running:
            try:
                # 寻找 Loopback 设备
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                device_info = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])

                if not device_info["isLoopbackDevice"]:
                    for loopback in p.get_loopback_device_info_generator():
                        if device_info["name"] in loopback["name"]:
                            device_info = loopback
                            break

                self.status_updated.emit(f"Listening: {device_info['name']}")

                sys_rate = int(device_info["defaultSampleRate"])
                channels = device_info["maxInputChannels"]

                stream = p.open(format=pyaudio.paInt16, channels=channels, rate=sys_rate,
                                input=True, input_device_index=device_info["index"],
                                frames_per_buffer=1024)

                frames = []
                frames_needed = int(sys_rate * BUFFER_DURATION / 1024)

                logging.info(f"Capture started on {device_info['name']}")

                while self.running:
                    data = stream.read(1024, exception_on_overflow=False)
                    frames.append(data)

                    if len(frames) >= frames_needed:
                        audio_bytes = b''.join(frames)
                        frames = []

                        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                        audio_float = audio_np.astype(np.float32) / 32768.0

                        if channels > 1:
                            audio_float = audio_float.reshape(-1, channels).mean(axis=1)

                        if sys_rate != SAMPLE_RATE:
                            # 简单的降采样优化
                            if sys_rate % SAMPLE_RATE == 0:
                                step = sys_rate // SAMPLE_RATE
                                audio_float = audio_float[::step]
                            else:
                                num_samples = int(len(audio_float) * SAMPLE_RATE / sys_rate)
                                audio_float = signal.resample(audio_float, num_samples)

                        max_vol = np.max(np.abs(audio_float))
                        if max_vol < 0.01:
                            continue
                        elif max_vol < 0.5:
                            audio_float = audio_float * (0.8 / (max_vol + 1e-6))
                            audio_float = np.clip(audio_float, -1.0, 1.0)

                        if not self.audio_queue.full():
                            self.audio_queue.put({"data": audio_float})

            except Exception as e:
                logging.error(f"Capture Error: {e}")
                time.sleep(2)
            finally:
                try:
                    stream.stop_stream()
                    stream.close()
                except:
                    pass

    def stop(self):
        self.running = False
        self.wait()