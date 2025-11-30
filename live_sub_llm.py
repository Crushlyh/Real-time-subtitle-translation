import sys
import time
import os
import logging
import numpy as np
import pyaudiowpatch as pyaudio
from scipy import signal
from faster_whisper import WhisperModel
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPoint
from openai import OpenAI

from log.logger_config import setup_logging
# ================= 配置区域 (请根据您的环境修改) =================

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
WHISPER_SIZE = "medium"  # 既然有LLM做后处理，Whisper可以用medium提速
DEVICE = "cuda"
BUFFER_DURATION = 1.5


# =============================================================
# 初始化日志
setup_logging()


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
            self.status_updated.emit("Whisper 加载失败")
            return

        client = None
        try:
            logging.info(f"正在连接 LLM: {LLM_BASE_URL}")
            client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
            client.models.list()
            logging.info("LLM 连接成功")
        except Exception as e:
            logging.warning(f"本地 LLM 连接失败: {e}")
            self.status_updated.emit("⚠️ 本地 LLM 未连接")

        p = pyaudio.PyAudio()

        while True:
            try:
                # 寻找设备逻辑
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                default_device_index = wasapi_info["defaultOutputDevice"]
                device_info = p.get_device_info_by_index(default_device_index)

                if not device_info["isLoopbackDevice"]:
                    for loopback in p.get_loopback_device_info_generator():
                        if device_info["name"] in loopback["name"]:
                            device_info = loopback
                            break

                current_device_name = device_info['name']
                # 使用 logging 记录
                logging.info(f"绑定音频设备: {current_device_name} (Index: {device_info['index']})")
                self.status_updated.emit(f"正在监听: {current_device_name}")

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

                logging.info("开始采集音频流...")

                while True:
                    try:
                        data = stream.read(1024, exception_on_overflow=False)
                        frames.append(data)
                    except (OSError, IOError) as e:
                        logging.warning(f"音频流异常: {e}")
                        break

                    if len(frames) >= frames_needed:
                        audio_bytes = b''.join(frames)
                        frames = []

                        audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                        audio_float = audio_np.astype(np.float32) / 32768.0

                        if channels > 1:
                            audio_float = audio_float.reshape(-1, channels).mean(axis=1)

                        if sys_rate != target_rate:
                            num_samples = int(len(audio_float) * target_rate / sys_rate)
                            audio_float = signal.resample(audio_float, num_samples)
                            audio_float = np.clip(audio_float, -1.0, 1.0)

                        if np.max(np.abs(audio_float)) < 0.01:
                            continue

                        segments, _ = whisper.transcribe(
                            audio_float,
                            beam_size=5,
                            vad_filter=True,
                            vad_parameters=dict(min_silence_duration_ms=400),
                            condition_on_previous_text=False
                        )

                        raw_text = " ".join([s.text for s in segments]).strip()

                        if len(raw_text) < 2: continue

                        logging.info(f"[原文] {raw_text}")

                        final_text = raw_text
                        if client:
                            try:
                                completion = client.chat.completions.create(
                                    model=LLM_MODEL_NAME,
                                    messages=[
                                        {"role": "system", "content": "翻译成中文。简练。"},
                                        {"role": "user", "content": raw_text}
                                    ],
                                    temperature=0.1,
                                    max_tokens=60
                                )
                                trans_text = completion.choices[0].message.content.strip()
                                logging.info(f"[译文] {trans_text}")
                                final_text = trans_text
                            except Exception as e:
                                logging.error(f"LLM 请求失败: {e}")

                        self.text_updated.emit(final_text)

                stream.stop_stream()
                stream.close()
                logging.info("重连设备中...")
                time.sleep(1)

            except Exception as e:
                logging.critical(f"主循环崩溃: {e}", exc_info=True)
                time.sleep(2)


# --- UI 部分 (保持不变，美化一下) ---
class SubtitleWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle('AI 实时字幕')

        layout = QVBoxLayout()
        self.label = QLabel("AI 听译准备中...", self)

        # 样式微调：加个金色边框更有科技感
        self.label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-family: "Microsoft YaHei UI", SimHei;
                font-size: 24px;
                font-weight: 600;
                background-color: rgba(0, 0, 0, 180);
                border: 1px solid rgba(255, 255, 255, 50);
                border-radius: 10px;
                padding: 15px;
            }
        """)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)

        layout.addWidget(self.label)
        self.setLayout(layout)

        screen = QApplication.primaryScreen().geometry()
        self.resize(900, 130)
        self.move((screen.width() - 900) // 2, screen.height() - 250)

    def update_text(self, text):
        self.label.setText(text)

    # 拖动逻辑
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            delta = QPoint(event.globalPos() - self.oldPos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPos()


def main():
    app = QApplication(sys.argv)
    window = SubtitleWindow()
    window.show()
    worker = AudioWorker()
    worker.text_updated.connect(window.update_text)
    worker.start()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()