"""Structured logging.

Every record carries the run identifier and the versions in force. This is
what makes a report defensible eighteen months later: the trace answers which
prompt, which model and which taxonomy produced a given claim.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_configured = False


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    """Configure structlog once per process.

    Console rendering is the default because the primary consumer is a
    reviewer watching a demo. ``json_output`` is what a deployed run would
    use, emitting to the trace table described in architecture section 10.
    """
    global _configured
    if _configured:
        return

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper()),
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        cache_logger_on_first_use=True,
    )
    _configured = True


def bind_run_context(**kwargs: Any) -> None:
    """Attach run-scoped identifiers to every subsequent log record.

    Called once at the start of a run with ``run_id``, ``taxonomy_version``,
    ``prompt_version`` and ``model``, so no call site has to remember to pass
    them and no record can omit them.
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_run_context() -> None:
    """Drop run-scoped identifiers. Used between runs in the same process."""
    structlog.contextvars.clear_contextvars()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for a module."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
