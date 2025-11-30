from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt5.QtCore import Qt, QPoint


class SubtitleWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.oldPos = self.pos()

    def initUI(self):
        # --- 窗口属性 ---
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle('AI 实时字幕')

        # --- 布局与控件 ---
        layout = QVBoxLayout()

        # 1. 状态栏 (小字体)
        self.status_label = QLabel("正在初始化...", self)
        self.status_label.setStyleSheet("color: #AAAAAA; font-size: 10px; background: transparent;")
        self.status_label.setFixedHeight(15)

        # 2. 主字幕 (大字体)
        self.label = QLabel("字幕准备就绪", self)
        self.label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-family: "Microsoft YaHei UI", SimHei;
                font-size: 28px;
                font-weight: 600;
                background-color: rgba(0, 0, 0, 160);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 12px;
                padding: 12px;
            }
        """)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)

        layout.addWidget(self.status_label)
        layout.addWidget(self.label)
        self.setLayout(layout)

        # --- 默认位置 (屏幕底部居中) ---
        screen = QApplication.primaryScreen().geometry()
        width, height = 900, 150
        self.resize(width, height)
        self.move((screen.width() - width) // 2, screen.height() - 250)

    # --- 槽函数：接收 Logic 发来的信号 ---
    def update_text(self, text):
        self.label.setText(text)

    def update_status(self, text):
        self.status_label.setText(text)

    # --- 鼠标拖动逻辑 ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            delta = QPoint(event.globalPos() - self.oldPos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPos()