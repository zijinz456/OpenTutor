"""Structured logging configuration using structlog.

Provides JSON output in production, colored console in development.
Binds request_id, user_id, course_id as context variables for tracing.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

from config import settings

# ── Context variables for request-scoped data ──

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")
course_id_var: ContextVar[str] = ContextVar("course_id", default="")


def generate_request_id() -> str:
    """Generate a short request ID for tracing."""
    return uuid.uuid4().hex[:12]


def _add_context_vars(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Inject context variables into every log event."""
    rid = request_id_var.get("")
    if rid:
        event_dict["request_id"] = rid
    uid = user_id_var.get("")
    if uid:
        event_dict["user_id"] = uid
    cid = course_id_var.get("")
    if cid:
        event_dict["course_id"] = cid
    return event_dict


def _add_app_info(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add application metadata."""
    event_dict["app"] = "opentutor"
    event_dict["env"] = settings.environment
    return event_dict


def configure_logging() -> None:
    """Set up structlog with stdlib integration.

    - Development: colored, human-readable console output.
    - Production: JSON lines to stdout.
    """
    is_prod = settings.environment == "production"

    # Shared processors
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_context_vars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if is_prod:
        shared_processors.append(_add_app_info)
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging to use structlog formatting
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    # Replace root handler
    root = logging.getLogger()
    root.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # Set log level
    log_level = logging.DEBUG if settings.environment == "development" else logging.INFO
    root.setLevel(log_level)

    # Quiet noisy third-party loggers
    for noisy in ("uvicorn.access", "httpcore", "httpx", "openai", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Add file handler if configured
    if settings.log_file:
        try:
            import os
            os.makedirs(os.path.dirname(settings.log_file) or ".", exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                settings.log_file,
                maxBytes=settings.log_max_bytes,
                backupCount=settings.log_backup_count,
                encoding="utf-8",
            )
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except OSError as exc:
            root.warning("Failed to set up log file %s: %s", settings.log_file, exc)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger bound to the given name."""
    return structlog.get_logger(name)
