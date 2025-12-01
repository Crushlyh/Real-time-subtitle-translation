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
    volume_updated = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self.running = True
        self.paused = False
        self.audio_queue = queue.Queue(maxsize=10)
        self.history_context = []

        # ★★★ 新增：语言状态管理 ★★★
        # 对应 UI 里的: ["Auto", "Zh", "En", "Ja", "Ko"]
        self.src_lang_map = [None, "zh", "en", "ja", "ko"]
        # 对应 UI 里的: ["Zh", "En", "Ja", "Ko"]
        self.tgt_lang_map = ["中文", "English", "Japanese", "Korean"]

        # 默认值
        self.current_src_lang = None  # Auto
        self.current_tgt_lang = "中文"

    # ★★★ 新增：接收 UI 发来的语言变更信号 ★★★
    def update_languages(self, src_idx, tgt_idx):
        try:
            self.current_src_lang = self.src_lang_map[src_idx]
            self.current_tgt_lang = self.tgt_lang_map[tgt_idx]
            logging.info(f"语言设置变更: 源=[{self.current_src_lang}] -> 目标=[{self.current_tgt_lang}]")

            # 清空历史上下文，防止不同语言混淆
            self.history_context = []
        except IndexError:
            pass

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

            # --- A. Whisper 识别 (带语言参数) ---
            try:
                segments, _ = whisper.transcribe(
                    audio_float,
                    beam_size=5,
                    # ★★★ 关键修改：传入当前选择的源语言 ★★★
                    # 如果是 None，Whisper 会自动检测
                    language=self.current_src_lang,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=MIN_SILENCE_MS),
                    condition_on_previous_text=False
                )
                raw_text = " ".join([s.text for s in segments]).strip()
            except Exception as e:
                logging.error(f"Transcribe Error: {e}")
                continue

            if len(raw_text) < 2: continue

            # --- B. LLM 翻译 (动态 Prompt) ---
            final_text = raw_text
            if client:
                try:
                    context_list = self.history_context[-3:]
                    context_str = " | ".join(context_list) if context_list else "无"

                    # ★★★ 关键修改：Prompt 中插入目标语言 ★★★
                    system_prompt = f"""
        你是一位资深同声传译。
        任务：将输入的【{self.current_src_lang if self.current_src_lang else '语音内容'}】翻译成地道的【{self.current_tgt_lang}】。

        【规则】：
        1. 风格口语化，自然流畅，拒绝机翻感。
        2. 结合上下文意译。
        3. 自动修正语音识别错误。
        4. 严禁输出"好的"、"翻译如下"等废话。
        5. 如果输入是乱码或噪音，输出"..."。
        6. 对于一些语气助词不要进行联想翻译
        7. 翻译间接明了，但同时做到不遗漏

        【上下文】：{context_str}
        """
                    completion = client.chat.completions.create(
                        model=LLM_MODEL_NAME,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": raw_text}
                        ],
                        temperature=0.2, max_tokens=100
                    )

                    final_text = completion.choices[0].message.content.strip()
                    final_text = final_text.replace("翻译：", "").replace("译文：", "")

                    self.history_context.append(final_text)
                    if len(self.history_context) > 10: self.history_context.pop(0)

                except Exception as e:
                    logging.error(f"LLM Error: {e}")

            self.text_updated.emit(raw_text, final_text)

    def capture_audio_loop(self):
        p = pyaudio.PyAudio()

        while self.running:
            if self.paused:
                time.sleep(0.1)
                continue
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
                    # ★★★ 3. 暂停逻辑 ★★★
                    if self.paused:
                        time.sleep(0.1)
                        # 发送 0 音量，让进度条归零
                        self.volume_updated.emit(0.0)
                        continue

                    data = stream.read(1024, exception_on_overflow=False)
                    frames.append(data)

                    # ★★★ 4. 计算实时音量并发送 ★★★
                    # 简单取一段数据算音量，为了性能不需要非常精确
                    temp_np = np.frombuffer(data, dtype=np.int16)
                    temp_float = temp_np.astype(np.float32) / 32768.0
                    vol = np.max(np.abs(temp_float))
                    self.volume_updated.emit(vol)

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

                        # ★ 新增：发送音量信号给 UI 画波形
                        self.volume_updated.emit(max_vol)

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

    # ★★★ 5. 切换暂停方法 ★★★
    def toggle_pause(self):
        self.paused = not self.paused
        logging.info(f"暂停状态切换: {self.paused}")