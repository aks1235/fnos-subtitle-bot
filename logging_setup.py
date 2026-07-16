"""日志初始化：stdout + 轮转文件双写。"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "/logs"
LOG_FILE = os.path.join(LOG_DIR, "bot.log")


def setup_logging(level: str = "INFO") -> None:
    """配置全局日志：stdout 供 docker logs，轮转文件供历史追溯。"""
    log_level = getattr(logging, level, logging.INFO)

    # 确保日志目录存在（容器内 /logs 由 compose 挂载，兜底创建）
    os.makedirs(LOG_DIR, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(log_level)
    # 清除可能已存在的 handler，避免重复
    root.handlers.clear()

    # stdout handler（docker logs -f 可见）
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    stream.setLevel(log_level)
    root.addHandler(stream)

    # 轮转文件 handler：5MB × 3 份
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(log_level)
        root.addHandler(file_handler)
    except (PermissionError, OSError) as e:
        # /logs 不可写时退化到仅 stdout，不阻断启动
        root.warning("无法写入日志文件 %s: %s，仅使用 stdout", LOG_FILE, e)
