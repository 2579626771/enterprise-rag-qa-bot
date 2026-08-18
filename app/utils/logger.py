import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import LOG_DIR

def get_logger(name:str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:    #防止重复添加 handler
        return logger
    
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )    #设置日志格式:时间 | 日志级别 | 日志名称 | 日志内容

    handler = logging.StreamHandler()   # StreamHandler() 表示输出到终端
    handler.setFormatter(formatter)   #让这个终端输出按照刚才定义的格式显示
    logger.addHandler(handler)   #把“输出到终端”这个能力绑定到logger 上

    try:
        log_dir = Path(LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "backend.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass
    return logger
