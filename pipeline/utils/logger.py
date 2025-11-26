import logging
import os
from typing import Optional


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Configure a console logger compatible with GitHub Actions."""
    logger_name = name or "pipeline"
    logger = logging.getLogger(logger_name)

    if logger.handlers:
        return logger

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="[%(asctime)s] %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    logger.debug("Logger initialized at level %s", level)
    return logger
