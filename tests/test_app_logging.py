import hashlib
import json
import logging
from unittest.mock import patch

from starlette.requests import Request

from naswa_matcher.app_logging import (
    JsonFormatter,
    configure_logging,
    log_event,
    log_exception,
    log_request,
    request_url,
    visitor_id_from_session_id,
)

# ── Test helpers ──────────────────────────────────────────────────────────────


def make_request(
    *,
    path: str = "/chat",
    query_string: bytes = b"",
    method: str = "GET",
) -> Request:
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query_string,
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
        }
    )

    request.state.request_id = "request-123"
    request.state.visitor_id = "visitor-456"

    return request


# ── Identity helpers ──────────────────────────────────────────────────────────


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


# ── JSON formatting ───────────────────────────────────────────────────────────


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


# ── Logging configuration ─────────────────────────────────────────────────────


def test_configure_logging_can_disable_named_logger():
    logger_name = "test.disabled.logger"
    target_logger = logging.getLogger(logger_name)

    original_disabled = target_logger.disabled

    try:
        configure_logging(
            root_level="INFO",
            disabled_loggers={logger_name},
        )

        assert target_logger.disabled is True

    finally:
        target_logger.disabled = original_disabled


# ── Request context helpers ───────────────────────────────────────────────────


def test_request_url_preserves_query_string():
    request = make_request(
        path="/opportunities",
        query_string=b"ranked=true&likes=computers&dislikes=office%2C+desk+work",
    )

    assert request_url(request) == (
        "/opportunities" "?ranked=true&likes=computers&dislikes=office%2C+desk+work"
    )


# ── Structured log helpers ────────────────────────────────────────────────────


def test_log_request_writes_structured_request():
    request = make_request(
        path="/opportunities/example-job",
    )

    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        log_request(
            request,
            action="pageview",
            status_code=200,
            duration_ms=18.437,
        )

    payload = log_info.call_args.kwargs["extra"]["structured"]

    assert payload == {
        "record_type": "request",
        "request_id": "request-123",
        "visitor_id": "visitor-456",
        "method": "GET",
        "url": "/opportunities/example-job",
        "action": "pageview",
        "status_code": 200,
        "duration_ms": 18.4,
    }


def test_log_event_writes_structured_event():
    request = make_request(
        path="/chat",
        method="POST",
    )

    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        log_event(
            request,
            "user_message_sent",
            message="Paulo",
            message_role="user",
        )

    log_info.assert_called_once()

    payload = log_info.call_args.kwargs["extra"]["structured"]

    assert payload == {
        "record_type": "event",
        "request_id": "request-123",
        "visitor_id": "visitor-456",
        "action": "user_message_sent",
        "method": "POST",
        "url": "/chat",
        "message": "Paulo",
        "message_role": "user",
    }


def test_log_event_does_not_allow_context_fields_to_be_overridden():
    request = make_request()

    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        log_event(
            request,
            "chat_reset",
            visitor_id="fake-visitor",
            request_id="fake-request",
            method="FAKE",
            url="/fake",
            record_type="fake-type",
        )

    payload = log_info.call_args.kwargs["extra"]["structured"]

    assert payload["visitor_id"] == "visitor-456"
    assert payload["request_id"] == "request-123"
    assert payload["method"] == "GET"
    assert payload["url"] == "/chat"
    assert payload["action"] == "chat_reset"
    assert payload["record_type"] == "event"


def test_log_exception_includes_request_context():
    request = make_request()

    with patch("naswa_matcher.app_logging.logger.exception") as log_exception_mock:
        try:
            raise RuntimeError("Bedrock unavailable")
        except RuntimeError:
            log_exception(
                request,
                "chat_agent_failed",
                error="RuntimeError: Bedrock unavailable",
                model="test-model",
            )

    payload = log_exception_mock.call_args.kwargs["extra"]["structured"]

    assert payload["record_type"] == "error"
    assert payload["action"] == "chat_agent_failed"
    assert payload["request_id"] == "request-123"
    assert payload["visitor_id"] == "visitor-456"
    assert payload["error"] == "RuntimeError: Bedrock unavailable"
    assert payload["model"] == "test-model"
