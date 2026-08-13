import logging

def get_logger(name:str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:    #防止重复添加 handler
        return logger
    
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler()   # StreamHandler() 表示输出到终端
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        )    #设置日志格式:时间 | 日志级别 | 日志名称 | 日志内容
    handler.setFormatter(formatter)   #让这个终端输出按照刚才定义的格式显示
    logger.addHandler(handler)   #把“输出到终端”这个能力绑定到logger 上
    return logger