import sys
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from PyQt5.QtCore import Qt, QPoint


class SubtitleWindow(QWidget):
    def __init__(self):
        super().__init__()

        # --- 状态变量 ---
        self.font_size_origin = 18
        self.font_size_trans = 30
        self.last_origin = "Waiting for audio..."
        self.last_trans = "等待音频输入..."
        self.current_opacity = 1.0  # 记录当前透明度

        self.initUI()
        self.oldPos = self.pos()

    def initUI(self):
        # --- 窗口属性 ---
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle('AI 实时字幕')

        # --- 主容器布局 ---
        # 我们使用一个主 QVBoxLayout，里面放两层：
        # 1. 顶部控制栏 (QHBoxLayout)
        # 2. 下方字幕区域 (QLabel)
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)  # 消除最外层边距
        self.main_layout.setSpacing(0)

        # --- 【背景容器】 ---
        # 为了让标题栏和字幕看起来是一体的，我们在主布局里放一个 Widget 作为背景
        self.container = QWidget()
        self.container.setStyleSheet("""
            QWidget {
                background-color: rgba(70, 65, 60, 195); /* 深莫兰迪暖灰背景 */
                border: 1px solid rgba(200, 190, 180, 50); /* 柔和边框 */
                border-radius: 15px;
            }
        """)

        # 容器内部布局
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(15, 10, 15, 15)  # 内部留白

        # ====================
        # Part 1: 顶部控制栏
        # ====================
        self.top_bar = QHBoxLayout()

        # 1.1 左侧状态文字
        self.status_label = QLabel("Ready", self)
        self.status_label.setStyleSheet("color: #AAAAAA; font-size: 11px; border: none; background: transparent;")
        self.status_label.setFixedHeight(20)

        # 1.2 右侧按钮组
        # 辅助函数：快速创建样式统一的小按钮
        def create_btn(text, tooltip, callback):
            btn = QPushButton(text)
            btn.setFixedSize(24, 24)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            # 按钮样式：平时透明，鼠标悬停变色
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

        # 创建按钮
        btn_font_up = create_btn("A+", "放大字体", self.increase_font)
        btn_font_down = create_btn("A-", "缩小字体", self.decrease_font)
        btn_opacity = create_btn("👁", "调节透明度", self.toggle_opacity)
        btn_close = create_btn("✕", "退出程序", self.close_app)
        # 给关闭按钮单独加一个红色悬停效果
        btn_close.setStyleSheet(
            btn_close.styleSheet().replace("QPushButton:hover {", "QPushButton:hover { color: #FF6666; "))

        # 组装顶部栏
        self.top_bar.addWidget(self.status_label)
        self.top_bar.addStretch()  # 弹簧，把按钮顶到右边
        self.top_bar.addWidget(btn_font_up)
        self.top_bar.addWidget(btn_font_down)
        self.top_bar.addWidget(btn_opacity)
        self.top_bar.addWidget(btn_close)

        # ====================
        # Part 2: 字幕显示区
        # ====================
        self.label = QLabel(self)
        self.label.setStyleSheet("border: none; background: transparent;")  # 移除Label自带背景，使用Container的
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)

        # 初始刷新
        self.refresh_display()

        # ====================
        # 组装整体
        # ====================
        self.container_layout.addLayout(self.top_bar)
        self.container_layout.addWidget(self.label)

        self.main_layout.addWidget(self.container)
        self.setLayout(self.main_layout)

        # --- 窗口大小与位置 ---
        screen = QApplication.primaryScreen().geometry()
        width, height = 900, 180
        self.resize(width, height)
        self.move((screen.width() - width) // 2, screen.height() - 300)

    # --- 功能逻辑 ---

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
        # 状态文字太长的话截断一下，防止挤压按钮
        if len(text) > 30: text = text[:28] + "..."
        self.status_label.setText(text)

    # --- 按钮回调函数 ---

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
        # 循环切换透明度: 1.0 -> 0.8 -> 0.5 -> 1.0
        if self.current_opacity > 0.9:
            self.current_opacity = 0.8
        elif self.current_opacity > 0.6:
            self.current_opacity = 0.5
        else:
            self.current_opacity = 1.0

        self.setWindowOpacity(self.current_opacity)
        self.status_label.setText(f"Opacity: {int(self.current_opacity * 100)}%")

    def close_app(self):
        QApplication.instance().quit()

    # --- 鼠标拖动逻辑 (只允许拖动背景，不影响按钮点击) ---
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 只有当鼠标点在"背景"上时才记录位置，点在按钮上会被按钮事件拦截
            self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            delta = QPoint(event.globalPos() - self.oldPos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPos()