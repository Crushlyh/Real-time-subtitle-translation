import sys
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QProgressBar, \
    QComboBox
from PyQt5.QtCore import Qt, QPoint, pyqtSignal
from PyQt5.QtGui import QFont


class SubtitleWindow(QWidget):
    pause_signal = pyqtSignal()
    language_signal = pyqtSignal(int, int)

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
        # --- 窗口属性 ---
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle('AI 实时字幕')

        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # --- 背景容器 ---
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

        # ====================
        # Part 1: 顶部控制栏
        # ====================
        self.top_bar = QHBoxLayout()

        # 1.1 左侧状态文字
        self.status_label = QLabel("Ready", self)
        self.status_label.setStyleSheet(
            "color: #AAAAAA; font-family: 'Segoe UI'; font-size: 11px; border: none; background: transparent;")
        self.status_label.setFixedHeight(20)

        # ★★★ 优化重点：下拉框样式 ★★★
        # 1. 字体：使用 Segoe UI / 微软雅黑
        # 2. 背景：半透明白色，制造磨砂感
        # 3. 下拉列表：深灰色背景，高亮色为莫兰迪绿
        combo_style = """
            QComboBox {
                background-color: rgba(255, 255, 255, 15); /* 极淡的半透明背景 */
                color: #E0E0E0;                              /* 字体颜色：灰白 */
                border: 1px solid rgba(255, 255, 255, 20);   /* 极细的描边 */
                border-radius: 6px;                          /* 胶囊圆角 */
                padding: 2px 10px 2px 10px;                  /* 内边距 */
                font-family: "Segoe UI", "Microsoft YaHei UI";
                font-size: 12px;
                min-width: 50px;
            }
            QComboBox:hover {
                background-color: rgba(255, 255, 255, 30);   /* 悬停变亮 */
                border: 1px solid rgba(255, 255, 255, 50);
            }
            QComboBox::drop-down {
                border: none; /* 隐藏默认的下拉按钮边框 */
                width: 15px;
            }
            /* 下拉箭头颜色 */
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #AAAAAA; /* 手画一个小三角 */
                margin-right: 5px;
            }
            /* 展开后的列表样式 */
            QComboBox QAbstractItemView {
                background-color: #2D2D2D;    /* 列表深色背景 */
                color: #DDDDDD;               /* 列表文字颜色 */
                border: 1px solid #444444;
                selection-background-color: #5A6A60; /* 选中项背景：莫兰迪绿 */
                selection-color: #FFFFFF;
                outline: none;
            }
        """

        # 源语言
        self.combo_src = QComboBox()
        self.combo_src.addItems(["Auto", "Zh", "En", "Ja", "Ko"])
        self.combo_src.setStyleSheet(combo_style)
        self.combo_src.setToolTip("源语言 (Source)")
        self.combo_src.setCursor(Qt.PointingHandCursor)
        self.combo_src.currentIndexChanged.connect(self.emit_lang_change)

        # 中间连接符 (优化字体颜色，更低调)
        arrow_label = QLabel("›")
        arrow_label.setStyleSheet(
            "color: #666666; font-size: 16px; font-weight: bold; border: none; background: transparent;")

        # 目标语言
        self.combo_tgt = QComboBox()
        self.combo_tgt.addItems(["Zh", "En", "Ja", "Ko"])
        self.combo_tgt.setStyleSheet(combo_style)
        self.combo_tgt.setToolTip("目标语言 (Target)")
        self.combo_tgt.setCursor(Qt.PointingHandCursor)
        self.combo_tgt.currentIndexChanged.connect(self.emit_lang_change)

        # 按钮创建函数
        def create_btn(text, tooltip, callback):
            btn = QPushButton(text)
            btn.setFixedSize(24, 24)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            # 按钮字体也统一一下
            btn.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #999999;
                    border: none;
                    font-family: "Segoe UI Symbol"; 
                    font-size: 15px;
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

        self.btn_pause = create_btn("⏸", "暂停/继续", self.on_pause_clicked)
        btn_font_up = create_btn("A+", "放大字体", self.increase_font)
        btn_font_down = create_btn("A-", "缩小字体", self.decrease_font)
        btn_opacity = create_btn("👁", "调节透明度", self.toggle_opacity)
        btn_close = create_btn("✕", "隐藏", self.close_app)
        btn_close.setStyleSheet(
            btn_close.styleSheet().replace("QPushButton:hover {", "QPushButton:hover { color: #FF6666; "))

        # 组装顶部栏
        self.top_bar.addWidget(self.status_label)
        self.top_bar.addStretch()

        # 语言选择区
        self.top_bar.addWidget(self.combo_src)
        self.top_bar.addSpacing(5)
        self.top_bar.addWidget(arrow_label)
        self.top_bar.addSpacing(5)
        self.top_bar.addWidget(self.combo_tgt)

        self.top_bar.addSpacing(15)  # 分隔线

        # 控制按钮区
        self.top_bar.addWidget(self.btn_pause)
        self.top_bar.addWidget(btn_font_up)
        self.top_bar.addWidget(btn_font_down)
        self.top_bar.addWidget(btn_opacity)
        self.top_bar.addWidget(btn_close)

        # ====================
        # Part 2: 字幕显示区
        # ====================
        self.label = QLabel(self)
        self.label.setStyleSheet("border: none; background: transparent;")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.refresh_display()

        # ====================
        # Part 3: 音量条
        # ====================
        self.volume_bar = QProgressBar(self.container)
        self.volume_bar.setFixedHeight(2)  # 更细一点，更精致
        self.volume_bar.setTextVisible(False)
        self.volume_bar.setRange(0, 100)
        self.volume_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: rgba(0,0,0,30);
                border-radius: 1px;
            }
            QProgressBar::chunk {
                background-color: #B5CABD; /* 莫兰迪绿 */
            }
        """)

        self.container_layout.addLayout(self.top_bar)
        self.container_layout.addWidget(self.label)
        self.container_layout.addWidget(self.volume_bar)

        self.main_layout.addWidget(self.container)
        self.setLayout(self.main_layout)

        screen = QApplication.primaryScreen().geometry()
        width, height = 900, 180
        self.resize(width, height)
        self.move((screen.width() - width) // 2, screen.height() - 300)

    # --- 槽函数保持不变 (emit_lang_change, update_text 等) ---
    def emit_lang_change(self):
        src_idx = self.combo_src.currentIndex()
        tgt_idx = self.combo_tgt.currentIndex()
        self.language_signal.emit(src_idx, tgt_idx)

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

    def on_pause_clicked(self):
        if self.btn_pause.text() == "⏸":
            self.btn_pause.setText("▶")
            self.update_status("已暂停 (省电模式)")
        else:
            self.btn_pause.setText("⏸")
            self.update_status("正在监听...")
        self.pause_signal.emit()

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
        self.hide()
        self.pause_signal.emit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.pause_signal.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            delta = QPoint(event.globalPos() - self.oldPos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPos()