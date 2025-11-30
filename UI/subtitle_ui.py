import sys
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QProgressBar
# ★★★ 1. 必须导入 pyqtSignal ★★★
from PyQt5.QtCore import Qt, QPoint, pyqtSignal


class SubtitleWindow(QWidget):
    # ★★★ 2. 必须在这里定义信号 (不能在 __init__ 里) ★★★
    pause_signal = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.font_size_origin = 18
        self.font_size_trans = 30
        self.last_origin = "Waiting for audio..."
        self.last_trans = "等待音频输入..."
        self.current_opacity = 1.0

        self.initUI()
        self.oldPos = self.pos()

    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle('AI 实时字幕')

        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.container = QWidget()
        self.container.setStyleSheet("""
            QWidget {
                background-color: rgba(70, 65, 60, 195);
                border: 1px solid rgba(200, 190, 180, 50);
                border-radius: 15px;
            }
        """)

        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(15, 10, 15, 15)

        # --- 顶部控制栏 ---
        self.top_bar = QHBoxLayout()
        self.status_label = QLabel("Ready", self)
        self.status_label.setStyleSheet("color: #AAAAAA; font-size: 11px; border: none; background: transparent;")
        self.status_label.setFixedHeight(20)

        def create_btn(text, tooltip, callback):
            btn = QPushButton(text)
            btn.setFixedSize(24, 24)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #999999;
                    border: none;
                    font-weight: bold;
                    font-size: 14px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 30);
                    color: #FFFFFF;
                }
                QPushButton:pressed {
                    background-color: rgba(255, 255, 255, 50);
                }
            """)
            btn.clicked.connect(callback)
            return btn

        # ★★★ 3. 添加暂停按钮 ★★★
        self.btn_pause = create_btn("⏸", "暂停/继续", self.on_pause_clicked)
        btn_font_up = create_btn("A+", "放大字体", self.increase_font)
        btn_font_down = create_btn("A-", "缩小字体", self.decrease_font)
        btn_opacity = create_btn("👁", "调节透明度", self.toggle_opacity)
        btn_close = create_btn("✕", "退出程序", self.close_app)
        btn_close.setStyleSheet(
            btn_close.styleSheet().replace("QPushButton:hover {", "QPushButton:hover { color: #FF6666; "))

        self.top_bar.addWidget(self.status_label)
        self.top_bar.addStretch()
        self.top_bar.addWidget(self.btn_pause)  # 加入布局
        self.top_bar.addWidget(btn_font_up)
        self.top_bar.addWidget(btn_font_down)
        self.top_bar.addWidget(btn_opacity)
        self.top_bar.addWidget(btn_close)

        # --- 字幕区 ---
        self.label = QLabel(self)
        self.label.setStyleSheet("border: none; background: transparent;")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.refresh_display()

        # --- 音量条 ---
        self.volume_bar = QProgressBar(self.container)
        self.volume_bar.setFixedHeight(3)
        self.volume_bar.setTextVisible(False)
        self.volume_bar.setRange(0, 100)
        self.volume_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: rgba(0,0,0,50);
                border-radius: 1px;
            }
            QProgressBar::chunk {
                background-color: #B5CABD;
            }
        """)

        self.container_layout.addLayout(self.top_bar)
        self.container_layout.addWidget(self.label)
        self.container_layout.addWidget(self.volume_bar)  # 加入音量条

        self.main_layout.addWidget(self.container)
        self.setLayout(self.main_layout)

        screen = QApplication.primaryScreen().geometry()
        width, height = 900, 180
        self.resize(width, height)
        self.move((screen.width() - width) // 2, screen.height() - 300)

    # --- 逻辑功能 ---
    def update_text(self, original_text, translated_text):
        self.last_origin = original_text
        self.last_trans = translated_text
        self.refresh_display()

    def refresh_display(self):
        color_origin = "#B5CABD"
        color_trans = "#E8D3C5"
        html_content = f"""
        <div style='line-height: 1.4;'>
            <span style='font-size: {self.font_size_origin}px; color: {color_origin}; font-family: "Segoe UI", Arial; font-weight: 500;'>
                {self.last_origin}
            </span>
            <br>
            <span style='font-size: {self.font_size_trans}px; color: {color_trans}; font-family: "Microsoft YaHei UI", SimHei; font-weight: bold; letter-spacing: 1px;'>
                {self.last_trans}
            </span>
        </div>
        """
        self.label.setText(html_content)

    def update_status(self, text):
        if len(text) > 30: text = text[:28] + "..."
        self.status_label.setText(text)

    # ★★★ 4. 暂停按钮回调 ★★★
    def on_pause_clicked(self):
        if self.btn_pause.text() == "⏸":
            self.btn_pause.setText("▶")
            self.update_status("已暂停 (省电模式)")
        else:
            self.btn_pause.setText("⏸")
            self.update_status("正在监听...")

        # 发送信号
        self.pause_signal.emit()

    # ★★★ 5. 音量更新回调 ★★★
    def update_volume(self, vol_float):
        display_vol = int(vol_float * 300)
        if display_vol > 100: display_vol = 100
        self.volume_bar.setValue(display_vol)

    def increase_font(self):
        self.font_size_trans += 2
        self.font_size_origin += 1
        self.refresh_display()

    def decrease_font(self):
        if self.font_size_trans > 12:
            self.font_size_trans -= 2
            self.font_size_origin -= 1
            self.refresh_display()

    def toggle_opacity(self):
        if self.current_opacity > 0.9:
            self.current_opacity = 0.8
        elif self.current_opacity > 0.6:
            self.current_opacity = 0.5
        else:
            self.current_opacity = 1.0
        self.setWindowOpacity(self.current_opacity)
        self.status_label.setText(f"Opacity: {int(self.current_opacity * 100)}%")

    def close_app(self):
        # 以前是 QApplication.instance().quit()
        # 现在改成：
        self.hide() # 隐藏窗口
        # 同时发送暂停信号，让后台停止录音省电
        self.pause_signal.emit()

    # 2. 新增：重写窗口关闭事件 (防止用户点任务栏关闭导致程序彻底退出)
    def closeEvent(self, event):
        event.ignore()  # 忽略系统的关闭请求
        self.hide()  # 改为隐藏
        self.pause_signal.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            delta = QPoint(event.globalPos() - self.oldPos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPos()