"""
Structured logging utility for all platform microservices.
Emits JSON-structured logs compatible with Loki label parsing and OTEL log pipelines.
Usage:
    from platform.logging.structured_logger import get_logger
    logger = get_logger("drift-monitor")
    logger.info("drift detected", psi=0.35, model="pod-failure-prediction", uc="UC1")
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

# Service metadata injected from environment (set in docker-compose / k8s env)
_SERVICE_NAME = os.getenv("SERVICE_NAME", "unknown-service")
_SERVICE_VERSION = os.getenv("SERVICE_VERSION", "unknown")
_ENVIRONMENT = os.getenv("ENVIRONMENT", "local")
_POD_NAME = os.getenv("POD_NAME", "")
_NODE_NAME = os.getenv("NODE_NAME", "")
_K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "")


class StructuredFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.
    Fields align with OpenTelemetry log data model for direct Loki ingestion.
    """

    LEVEL_MAP = {
        "DEBUG": "DEBUG",
        "INFO": "INFO",
        "WARNING": "WARN",
        "ERROR": "ERROR",
        "CRITICAL": "FATAL",
    }

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        log_entry: dict[str, Any] = {
            "timestamp": self._format_timestamp(record.created),
            "severity": self.LEVEL_MAP.get(record.levelname, record.levelname),
            "message": record.getMessage(),
            "logger": record.name,
            "service": {
                "name": _SERVICE_NAME,
                "version": _SERVICE_VERSION,
            },
            "environment": _ENVIRONMENT,
        }

        # Kubernetes context (empty strings are omitted)
        if _POD_NAME:
            log_entry["k8s"] = {
                "pod": _POD_NAME,
                "node": _NODE_NAME,
                "namespace": _K8S_NAMESPACE,
            }

        # Exception info
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Merge any structured kwargs passed via LoggerAdapter.extra or direct extra={}
        if hasattr(record, "structured_fields"):
            log_entry.update(record.structured_fields)  # type: ignore[attr-defined]

        # Standard log record extra fields (set via logger.info("msg", extra={"key": v}))
        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            "message",
            "structured_fields",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                try:
                    json.dumps(value)  # Only include JSON-serializable values
                    log_entry[key] = value
                except (TypeError, ValueError):
                    log_entry[key] = str(value)

        return json.dumps(log_entry, default=str, ensure_ascii=False)

    @staticmethod
    def _format_timestamp(created: float) -> str:
        """ISO-8601 UTC timestamp with millisecond precision."""
        t = time.gmtime(created)
        ms = int((created % 1) * 1000)
        return (
            f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
            f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}.{ms:03d}Z"
        )


class PlatformLogger(logging.Logger):
    """
    Extended logger that accepts structured keyword arguments.
    Usage: logger.info("msg", uc="UC1", psi=0.35, model="my-model")
    All kwargs are merged into the structured JSON output.
    """

    def _log_with_fields(self, level: int, msg: str, **kwargs: Any) -> None:
        extra = kwargs.pop("extra", {})
        extra["structured_fields"] = kwargs
        self._log(level, msg, (), extra=extra)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.DEBUG):
            self._log_with_fields(logging.DEBUG, msg, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.INFO):
            self._log_with_fields(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.WARNING):
            self._log_with_fields(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.ERROR):
            self._log_with_fields(logging.ERROR, msg, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        if self.isEnabledFor(logging.CRITICAL):
            self._log_with_fields(logging.CRITICAL, msg, **kwargs)


def get_logger(name: str | None = None, level: str | None = None) -> PlatformLogger:
    """
    Get a structured JSON logger for a given service/component name.

    Args:
        name: Logger name (service or module name). Defaults to SERVICE_NAME env var.
        level: Log level override. Falls back to LOG_LEVEL env var or INFO.

    Returns:
        PlatformLogger with structured JSON formatter bound to stdout.

    Example:
        logger = get_logger("drift-monitor")
        logger.info("drift check complete", uc="UC1", psi=0.35, retrain=True)
    """
    logger_name = name or _SERVICE_NAME
    log_level_str = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, log_level_str, logging.INFO)

    # Register PlatformLogger as the class for this logger
    logging.setLoggerClass(PlatformLogger)
    logger = logging.getLogger(logger_name)
    logging.setLoggerClass(logging.Logger)  # Reset to avoid affecting stdlib loggers

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.setLevel(numeric_level)
        logger.propagate = False

    return logger  # type: ignore[return-value]


def configure_root_logger(level: str = "INFO") -> None:
    """
    Replace the root logger's handlers with a structured JSON formatter.
    Call once at application startup (e.g., in FastAPI lifespan).
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root.addHandler(handler)
    root.setLevel(numeric_level)
