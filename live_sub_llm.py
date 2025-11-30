import sys
import time
import os
import numpy as np
import pyaudiowpatch as pyaudio
from scipy import signal
from faster_whisper import WhisperModel
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QPoint
from openai import OpenAI

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


# =============================================================

class AudioWorker(QThread):
    text_updated = pyqtSignal(str)

    def run(self):
        # --- 初始化 Whisper ---
        print(f"正在加载 Whisper ({WHISPER_SIZE})...")
        whisper = WhisperModel(WHISPER_SIZE, device=DEVICE, compute_type="float16")

        # --- 初始化 LLM 客户端 ---
        print(f"正在连接本地大模型: {LLM_BASE_URL}...")
        try:
            client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
            # 测试连接
            client.models.list()
            print("✅ 本地大模型连接成功！")
        except Exception as e:
            print(f"❌ 无法连接本地大模型: {e}")
            print("请检查 LM Studio/Ollama 是否已启动并开启 Server 模式")
            return

        # --- 初始化音频录制 (WASAPI Loopback) ---
        p = pyaudio.PyAudio()
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])

        if not default_speakers["isLoopbackDevice"]:
            for loopback in p.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    default_speakers = loopback
                    break

        print(f"🎤 监听设备: {default_speakers['name']}")

        sys_rate = int(default_speakers["defaultSampleRate"])
        channels = default_speakers["maxInputChannels"]
        target_rate = 16000

        stream = p.open(format=pyaudio.paInt16, channels=channels, rate=sys_rate,
                        input=True, input_device_index=default_speakers["index"],
                        frames_per_buffer=1024)

        frames = []
        chunk_duration = 1.5  # 3秒一切片
        frames_needed = int(sys_rate * chunk_duration / 1024)

        print("🚀 服务已启动，播放视频即可看到字幕...")

        while True:
            data = stream.read(1024, exception_on_overflow=False)
            frames.append(data)

            if len(frames) >= frames_needed:
                # 音频预处理 (Bytes -> Float32 -> Resample)
                audio_bytes = b''.join(frames)
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                audio_float = audio_np.astype(np.float32) / 32768.0

                if channels > 1:
                    audio_float = audio_float.reshape(-1, channels).mean(axis=1)

                if sys_rate != target_rate:
                    num_samples = int(len(audio_float) * target_rate / sys_rate)
                    audio_float = signal.resample(audio_float, num_samples)
                    audio_float = np.clip(audio_float, -1.0, 1.0)

                frames = []  # 清空缓冲

                if np.max(np.abs(audio_float)) < 0.01: continue

                # 1. Whisper 听写 (只负责听，不做翻译，task="transcribe")
                # 我们让 Whisper 尽可能忠实地记录原文
                segments, _ = whisper.transcribe(
                    audio_float,
                    beam_size=5,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500),
                    condition_on_previous_text=False
                )

                raw_text = " ".join([s.text for s in segments]).strip()

                # 过滤极短文本或幻觉
                if len(raw_text) < 2 or "订阅" in raw_text or "打赏" in raw_text:
                    continue

                print(f"👂 听到: {raw_text}")

                # 2. 调用本地大模型进行翻译/润色
                # 这里使用异步思维，但为了代码简单我们先同步调用
                # 4070S 跑 Qwen-14B 翻译一句话只需要几百毫秒
                try:
                    completion = client.chat.completions.create(
                        model=LLM_MODEL_NAME,
                        messages=[
                            {"role": "system",
                             "content": "你是一个专业的字幕翻译工具。将用户的输入直接翻译成中文。简练、准确。如果输入是乱码或无意义声音，请输出'...'。不要解释，只输出译文。"},
                            {"role": "user", "content": raw_text}
                        ],
                        temperature=0.3,  # 低温度保证稳定
                        max_tokens=100  # 字幕不需要太长
                    )
                    translated_text = completion.choices[0].message.content.strip()

                    if translated_text and translated_text != "...":
                        print(f"🤖 翻译: {translated_text}")
                        self.text_updated.emit(translated_text)

                except Exception as e:
                    print(f"LLM 调用失败: {e}")
                    # 如果 LLM 挂了，降级显示原文
                    self.text_updated.emit(raw_text)


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