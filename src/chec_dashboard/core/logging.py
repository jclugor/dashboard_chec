from __future__ import annotations

import logging


_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"



def configure_logging(level_name: str = "INFO") -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(level=level, format=_LOG_FORMAT)
        return

    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)
        if handler.formatter is None:
            handler.setFormatter(logging.Formatter(_LOG_FORMAT))



def get_logger(name: str, level_name: str = "INFO") -> logging.Logger:
    configure_logging(level_name)
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level_name.upper(), logging.INFO))
    return logger
