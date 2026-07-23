import hashlib
import json
import logging
from datetime import UTC, datetime


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
) -> logging.Logger:
    """Configure JSON logging and optional named logger levels."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, root_level, logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    for logger_name, level in (logger_levels or {}).items():
        logging.getLogger(logger_name).setLevel(getattr(logging, level, logging.INFO))

    return logging.getLogger("naswa")
