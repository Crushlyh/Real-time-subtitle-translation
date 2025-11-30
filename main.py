import sys
import logging
from live_sub_llm import AudioWorker

from PyQt5.QtWidgets import QApplication
from UI.subtitle_ui import SubtitleWindow
from log.logger_config import setup_logging


def main():
    # 1. 初始化日志系统
    log_path = setup_logging()

    # 2. 配置全局异常捕获 (Crash Handler)
    # 这一步非常重要，防止程序默默闪退而不报错
    def handle_exception(exc_type, exc_value, exc_traceback):
        # 如果是用户按 Ctrl+C，正常退出
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        # 其他错误记录到日志
        logging.critical("Uncaught Exception (程序崩溃):", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception
    logging.info(">>> 程序启动 <<<")

    # 3. 创建 Qt 应用实例
    app = QApplication(sys.argv)

    # 4. 实例化 UI (View)
    window = SubtitleWindow()
    window.show()
    logging.info("UI 窗口已显示")

    # 5. 实例化业务逻辑线程 (Model/Controller)
    worker = AudioWorker()

    # 6. 【关键】连接信号与槽 (Wiring)
    # 当 worker 发出 text_updated 信号时 -> 调用 window.update_text
    worker.text_updated.connect(window.update_text)
    worker.status_updated.connect(window.update_status)

    # 7. 启动后台线程
    worker.start()
    logging.info("后台音频线程已启动")

    # 8. 进入事件循环
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()