from unittest.mock import patch
from uuid import UUID


def structured_payloads(log_info):
    """Return structured payloads written through the application logger."""
    payloads = []

    for call in log_info.call_args_list:
        extra = call.kwargs.get("extra", {})
        structured = extra.get("structured")

        if isinstance(structured, dict):
            payloads.append(structured)

    return payloads


def event_payloads(log_info, action):
    """Return structured event payloads for one action."""
    return [
        payload
        for payload in structured_payloads(log_info)
        if payload.get("record_type") == "event" and payload.get("action") == action
    ]


def test_chat_post_logs_user_message_sent(client):
    message = "I love to make websites!"

    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        response = client.post(
            "/chat",
            data={"message": message},
        )

    assert response.status_code == 200

    events = event_payloads(log_info, "user_message_sent")

    assert len(events) == 1

    event = events[0]

    assert event["record_type"] == "event"
    assert event["action"] == "user_message_sent"
    assert event["method"] == "POST"
    assert event["url"] == "/chat"

    assert event["message_role"] == "user"
    assert event["message_sequence"] == 1
    assert event["message"] == message
    assert event["character_count"] == len(message)

    request_id = UUID(event["request_id"])

    assert request_id.version == 4

    assert len(event["visitor_id"]) == 64
    assert all(character in "0123456789abcdef" for character in event["visitor_id"])

    request_logs = [
        payload
        for payload in structured_payloads(log_info)
        if payload.get("record_type") == "request"
        and payload.get("url") == "/chat"
        and payload.get("method") == "POST"
    ]

    assert len(request_logs) == 1

    request_log = request_logs[0]

    assert request_log["request_id"] == event["request_id"]
    assert request_log["visitor_id"] == event["visitor_id"]


def test_chat_post_increments_user_message_sequence(client):
    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        first_response = client.post(
            "/chat",
            data={"message": "Paulo"},
        )
        second_response = client.post(
            "/chat",
            data={"message": "I like computers"},
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    events = event_payloads(log_info, "user_message_sent")

    assert len(events) == 2

    assert events[0]["message"] == "Paulo"
    assert events[0]["message_sequence"] == 1

    assert events[1]["message"] == "I like computers"
    assert events[1]["message_sequence"] == 2


def test_chat_post_does_not_log_empty_user_message(client):
    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        empty_response = client.post(
            "/chat",
            data={"message": "   "},
        )

        message_response = client.post(
            "/chat",
            data={"message": "Paulo"},
        )

    assert empty_response.status_code == 204
    assert message_response.status_code == 200

    events = event_payloads(log_info, "user_message_sent")

    assert len(events) == 1
    assert events[0]["message"] == "Paulo"
    assert events[0]["message_sequence"] == 1
