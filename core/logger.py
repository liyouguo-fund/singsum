"""
日志记录模块 - 支持控制台和文件双重输出

从 fund_signal 项目迁移，调整为项目根目录下的 logs/ 目录。
"""

import logging
import os
from datetime import datetime


class Logger:
    """日志记录器，支持控制台和文件输出"""

    def __init__(self, name='fund_analyzer', log_dir=None):
        """初始化日志记录器

        Args:
            name: 日志记录器名称
            log_dir: 日志目录路径，默认为项目根目录下的 logs/
        """
        if log_dir is None:
            # 获取项目根目录（core/ 的父目录）
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        # 创建日志目录
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # 生成日志文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = os.path.join(log_dir, f'运行日志_{timestamp}.log')
        self.log_file = log_file

        # 清除已有的处理器
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)

        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        # 格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        # 添加处理器
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)

    def debug(self, message):
        """记录DEBUG级别的日志"""
        self.logger.debug(message)

    def info(self, message):
        """记录INFO级别的日志"""
        self.logger.info(message)

    def warning(self, message):
        """记录WARNING级别的日志"""
        self.logger.warning(message)

    def error(self, message):
        """记录ERROR级别的日志"""
        self.logger.error(message)

    def get_log_file(self):
        """获取日志文件路径"""
        return self.log_file


# 创建全局日志记录器实例
logger = Logger()
