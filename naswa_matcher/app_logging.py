import hashlib
import json
import logging
from datetime import UTC, datetime

from fastapi import Request

logger = logging.getLogger("naswa")


def visitor_id_from_session_id(session_id: str) -> str:
    """Return a stable, non-reversible logging ID for a browser session."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def utc_timestamp() -> str:
    """Return the current UTC time as an ISO 8601 timestamp."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    """Format application log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": utc_timestamp(),
            "level": record.levelname,
        }

        structured = getattr(record, "structured", None)

        if isinstance(structured, dict):
            payload.update(structured)
        else:
            payload.update(
                {
                    "record_type": "application",
                    "logger": record.name,
                    "message": record.getMessage(),
                }
            )

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )


def configure_logging(
    *,
    root_level: str,
    logger_levels: dict[str, str] | None = None,
    disabled_loggers: set[str] | None = None,
) -> logging.Logger:
    """Configure JSON logging and optional named logger behavior."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, root_level, logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    for logger_name, level in (logger_levels or {}).items():
        logging.getLogger(logger_name).setLevel(
            getattr(logging, level, logging.INFO)
        )

    for logger_name in disabled_loggers or set():
        logging.getLogger(logger_name).disabled = True

    return logging.getLogger("naswa")


def request_url(request: Request) -> str:
    """Return the request path with its original query string."""
    path = request.url.path
    query = request.url.query

    return f"{path}?{query}" if query else path


def _request_fields(request: Request) -> dict:
    """Return structured fields shared by request and event logs."""
    return {
        "request_id": request.state.request_id,
        "visitor_id": request.state.visitor_id,
        "method": request.method,
        "url": request_url(request),
    }


def log_event(
    request: Request,
    action: str,
    **fields,
) -> None:
    """Write a structured application event associated with a request."""
    payload = {
        **fields,
        "record_type": "event",
        **_request_fields(request),
        "action": action,
    }

    logger.info("", extra={"structured": payload})


def log_request(
    request: Request,
    *,
    action: str,
    status_code: int,
    duration_ms: float,
) -> None:
    """Write a structured record for a completed HTTP request."""
    payload = {
        "record_type": "request",
        **_request_fields(request),
        "action": action,
        "status_code": status_code,
        "duration_ms": round(duration_ms, 1),
    }

    logger.info("", extra={"structured": payload})
