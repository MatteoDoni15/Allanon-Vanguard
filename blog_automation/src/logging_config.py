"""
Centralized logging configuration for the blog automation pipeline.

Logs are printed to stdout with INFO, WARNING, and ERROR levels.
Format: [LEVEL] [module] message
"""

import logging
import sys


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the root logger for the pipeline."""
    logger = logging.getLogger("blog_automation")
    logger.setLevel(level)

    # Remove any existing handlers to avoid duplicates
    logger.handlers.clear()

    # On Windows the console defaults to a legacy code page (cp1252) that can't
    # encode characters like → or emoji; reconfigure stdout to replace rather
    # than raise, so a stray non-ASCII char in a log message never crashes.
    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    # Console handler with readable format
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt="[%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def get_logger(module_name: str) -> logging.Logger:
    """Get a logger for a specific module."""
    return logging.getLogger(f"blog_automation.{module_name}")
