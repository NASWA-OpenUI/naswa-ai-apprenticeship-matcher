import hashlib
import json
import logging

from naswa_matcher.structured_logging import (
    JsonFormatter,
    visitor_id_from_session_id,
)


def test_visitor_id_from_session_id_is_deterministic():
    session_id = "a" * 43

    first = visitor_id_from_session_id(session_id)
    second = visitor_id_from_session_id(session_id)

    assert first == second


def test_visitor_id_from_session_id_differs_for_different_sessions():
    first = visitor_id_from_session_id("a" * 43)
    second = visitor_id_from_session_id("b" * 43)

    assert first != second


def test_visitor_id_from_session_id_uses_sha256():
    session_id = "a" * 43

    expected = hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    assert visitor_id_from_session_id(session_id) == expected


def test_json_formatter_formats_application_log():
    formatter = JsonFormatter()

    record = logging.LogRecord(
        name="naswa",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Application started",
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["record_type"] == "application"
    assert payload["logger"] == "naswa"
    assert payload["message"] == "Application started"
    assert payload["timestamp"].endswith("Z")


def test_json_formatter_formats_structured_log():
    formatter = JsonFormatter()

    record = logging.LogRecord(
        name="naswa",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    )

    record.structured = {
        "record_type": "event",
        "request_id": "request-123",
        "visitor_id": "visitor-123",
        "action": "chat_reset",
    }

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["record_type"] == "event"
    assert payload["request_id"] == "request-123"
    assert payload["visitor_id"] == "visitor-123"
    assert payload["action"] == "chat_reset"


def test_json_formatter_preserves_unicode():
    formatter = JsonFormatter()

    record = logging.LogRecord(
        name="naswa",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Jag gillar svensk mytologi — åäö",
        args=(),
        exc_info=None,
    )

    formatted = formatter.format(record)

    assert "svensk mytologi" in formatted
    assert "åäö" in formatted
    assert "\\u00e5" not in formatted
