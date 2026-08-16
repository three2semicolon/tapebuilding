"""Centralized logging configuration for tapebuilding."""

import logging
import sys

def get_logger(name: str = __name__) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        # Logger already configured
        return logger

    logger.setLevel(logging.INFO)

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)

    # Avoid duplicate handlers
    if not logger.handlers:
        logger.addHandler(handler)
        logger.propagate = False

    return logger