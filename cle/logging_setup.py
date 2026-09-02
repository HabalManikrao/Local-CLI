"""Structured logging setup.

Console logging goes through Rich for readable, colorized output. Log level is
driven by config (``logging.level``) or an explicit override (e.g. a global
``--verbose`` flag). Idempotent: repeated calls reconfigure the CLE logger
without stacking handlers.
"""

from __future__ import annotations

import logging

from rich.logging import RichHandler

_LOGGER_NAME = "cle"


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the root CLE logger."""
    logger = logging.getLogger(_LOGGER_NAME)
    numeric = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric)

    # Reset handlers so repeated setup() calls stay idempotent.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = RichHandler(
        rich_tracebacks=True,
        show_time=False,
        show_path=False,
        markup=False,
    )
    handler.setLevel(numeric)
    logger.addHandler(handler)
    # Prevent double emission via the root logger.
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child of the CLE logger (or the CLE logger itself)."""
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)
