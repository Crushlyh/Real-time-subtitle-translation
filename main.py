import sys
import os
import logging
import keyboard  # 用于监听全局热键

from log.logger_config import setup_logging
setup_logging()

from live_sub_llm import AudioWorker
from UI.subtitle_ui import SubtitleWindow
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction, QStyle
from PyQt5.QtGui import QIcon

# 定义全局热键 (你可以改成自己喜欢的，比如 'ctrl+alt+t')
HOTKEY = 'alt+q'
ICON_PATH = "icon.png"


def main():
    logging.info(">>> 记录日志 <<<")
    # 初始化日志系统
    sys.excepthook = handle_exception

    logging.info(">>> 程序启动 <<<")
    app = QApplication(sys.argv)

    # 设置缩小化图标
    if os.path.exists(ICON_PATH):
        # 如果找到了图片文件，就加载它
        app_icon = QIcon(ICON_PATH)
        app.setWindowIcon(app_icon)
    else:
        # 没找到文件，就用系统默认的，并在日志里吐槽一下
        logging.warning(f"未找到图标文件: {ICON_PATH}，将使用默认图标。")
        app_icon = app.style().standardIcon(QStyle.SP_ComputerIcon)

    # 初始化窗口和业务
    window = SubtitleWindow()
    window.show()
    logging.info("UI 窗口已显示")
    # 实例化业务逻辑线程
    worker = AudioWorker()
    worker.text_updated.connect(window.update_text)
    worker.status_updated.connect(window.update_status)
    # 连接音量信号 (Logic -> UI)
    worker.volume_updated.connect(window.update_volume)
    # 连接暂停信号 (UI -> Logic)
    # 注意：Qt 信号不能直接连类方法，最好用 lambda 或封装一层，这里直接连 worker.toggle_pause
    window.pause_signal.connect(worker.toggle_pause)
    # 启动后台线程
    worker.start()
    logging.info("后台音频线程已启动")

    # ★★★ 系统托盘 (System Tray) 设置 ★★★
    tray = QSystemTrayIcon(app)
    # 使用系统自带的一个标准图标 (SP_ComputerIcon)，你也可以换成自己的 .png
    tray.setIcon(app_icon)

    tray.setToolTip("AI 实时字幕翻译\n(双击显示/隐藏)")
    # 托盘右键菜单
    menu = QMenu()

    action_show = QAction("显示/隐藏字幕", app)
    action_show.triggered.connect(lambda: toggle_window)

    action_quit = QAction("彻底退出", app)
    action_quit.triggered.connect(app.quit)  # 只有点这个才是真退出

    menu.addAction(action_show)
    menu.addSeparator()
    menu.addAction(action_quit)

    tray.setContextMenu(menu)

    # ★ Feature B: 双击托盘图标事件, 作为匿名函数
    def on_tray_activated(reason):
        if reason == QSystemTrayIcon.DoubleClick:
            # 在这里把 main 函数里的 window 和 worker 传进去
            toggle_window(window, worker)

    tray.activated.connect(on_tray_activated)
    tray.show()

    # 气泡提示
    tray.showMessage(
        "AI 字幕已启动",
        f"按 {HOTKEY} 唤醒/隐藏字幕\n模型已在后台待命",
        QSystemTrayIcon.Information,
        3000
    )

    # 注册热键 (非阻塞)
    try:
        keyboard.add_hotkey(HOTKEY, lambda: toggle_window(window, worker))
        logging.info(f"全局热键 {HOTKEY} 已注册")
    except ImportError:
        logging.error("Keyboard 库未安装，全局热键失效")

    # 运行应用 防止窗口关闭导致退出
    app.setQuitOnLastWindowClosed(False)

    exit_code = app.exec_()
    sys.exit(exit_code)


def handle_exception(exc_type, exc_value, exc_traceback):
    # 如果是用户按 Ctrl+C，正常退出
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    # 其他错误记录到日志
    logging.critical("Uncaught Exception (程序崩溃):", exc_info=(exc_type, exc_value, exc_traceback))


def toggle_window(window, worker):
    if window.isVisible():
        # 隐藏并暂停
        window.hide()
        if not worker.paused:
            worker.toggle_pause()
            window.btn_pause.setText("▶")
            window.update_status("已隐藏 (休眠中)")
    else:
        # 显示并恢复
        window.showNormal()
        window.activateWindow()
        if worker.paused:
            worker.toggle_pause()
            window.btn_pause.setText("⏸")
            window.update_status("正在监听...")


if __name__ == "__main__":
    main()
