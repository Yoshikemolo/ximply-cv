"""
Logging configuration for the application.

Provides structured logging with configurable levels and formats.
"""

import logging
import sys
from typing import Optional

from app.core.config import settings


def setup_logging(level: Optional[str] = None) -> logging.Logger:
    """
    Configure application logging.

    Args:
        level: Optional log level override. Uses DEBUG in debug mode otherwise INFO.

    Returns:
        Logger: Configured root logger instance.
    """
    if level is None:
        level = "DEBUG" if settings.debug else "INFO"

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return logging.getLogger("ximply_vision")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.

    Args:
        name: Module name, typically __name__.

    Returns:
        Logger: Logger instance for the specified module.
    """
    return logging.getLogger(name)
