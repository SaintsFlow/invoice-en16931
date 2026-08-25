"""Logging setup. One JSON line per event, level taken from LOG_LEVEL."""

from __future__ import annotations

import logging
import os
import sys
from typing import Final, cast

import structlog
from structlog.typing import Processor

_LEVELS: Final[dict[str, int]] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

_DEFAULT_LEVEL: Final = "info"

# uvicorn installs handlers of its own and prints plain text. We take those
# handlers away, so every line on stdout is JSON no matter who wrote it.
_FOREIGN_LOGGERS: Final = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging() -> None:
    """Set up JSON logging. Calling it twice does no harm."""
    requested = os.getenv("LOG_LEVEL", _DEFAULT_LEVEL).strip().lower()
    level = _LEVELS.get(requested, logging.INFO)

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in _FOREIGN_LOGGERS:
        foreign = logging.getLogger(name)
        foreign.handlers.clear()
        foreign.propagate = True

    if requested not in _LEVELS:
        # A typo in LOG_LEVEL should not kill the service, but staying quiet
        # about it means guessing later why debug lines never showed up.
        get_logger().warning("log_level_unknown", value=requested, using=_DEFAULT_LEVEL)


def get_logger() -> structlog.stdlib.BoundLogger:
    """Return a logger bound to the current context."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger())
