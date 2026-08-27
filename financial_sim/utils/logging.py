"""Structured logging setup for FinancialSim.

Provides a consistent logging interface across all modules.
Uses stdlib logging with a simple, human-readable format by default.
"""
from __future__ import annotations

import logging
import sys
from typing import Final

_LOG_FORMAT: Final[str] = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    format_string: str | None = None,
) -> None:
    """Configure root logger.

    Parameters
    ----------
    level : str
        One of DEBUG/INFO/WARNING/ERROR/CRITICAL. Default "INFO".
    log_file : str | None
        If provided, also log to this file in addition to stderr.
    format_string : str | None
        Custom format string. If None, uses module default.
    """
    root = logging.getLogger("financial_sim")
    root.setLevel(level.upper())

    # Remove existing handlers (avoid duplicates when called twice)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    fmt = format_string or _LOG_FORMAT
    formatter = logging.Formatter(fmt, datefmt=_DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Don't propagate to Python root (avoid duplicate messages)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the 'financial_sim' namespace.

    Convention: pass __name__ from the calling module.

    Example:
        >>> from financial_sim.utils.logging import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("Starting simulation")
    """
    if not name.startswith("financial_sim"):
        name = f"financial_sim.{name}"
    return logging.getLogger(name)


# Configure default logging on import (only if not already configured)
_default_logger = logging.getLogger("financial_sim")
if not _default_logger.handlers:
    setup_logging()
