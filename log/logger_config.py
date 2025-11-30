import logging
import os
import sys
import datetime


def setup_logging(log_dir="logs"):
    """
    配置全局日志系统
    :param log_dir: 日志保存的目录名称，默认为 "logs"
    """
    # 1. 确保日志目录存在
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 2. 生成当天的日志文件名 (例如: logs/subtitle_2025-11-30.log)
    current_date = datetime.datetime.now().strftime('%Y-%m-%d')
    log_filename = f"subtitle_{current_date}.log"
    log_filepath = os.path.join(log_dir, log_filename)

    # 3. 配置 logging
    # 这里的配置是全局的，只要运行了这一步，后续所有文件里的 logging.info() 都会生效
    logging.basicConfig(
        level=logging.INFO,  # 设置记录级别
        format='%(asctime)s [%(levelname)s] %(message)s',  # 日志格式
        datefmt='%H:%M:%S',
        handlers=[
            logging.FileHandler(log_filepath, encoding='utf-8'),  # 写入文件
            logging.StreamHandler(sys.stdout)  # 输出到控制台
        ]
    )

    logging.info("=" * 30)
    logging.info("日志模块加载成功")
    logging.info(f"日志文件路径: {os.path.abspath(log_filepath)}")
    logging.info("=" * 30)

    # 返回日志路径，万一主程序想展示给用户看
    return log_filepath
