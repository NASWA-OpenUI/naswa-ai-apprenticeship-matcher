from unittest.mock import patch
from uuid import UUID

import server
from naswa_matcher.sessions import SESSION_COOKIE_NAME


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


def current_chat_session(client):
    """Return the server-side session belonging to the test browser."""
    session_id = client.cookies.get(SESSION_COOKIE_NAME)

    assert session_id is not None

    _session_id, session, _needs_cookie = server.session_store.get_or_create(session_id)

    return session


def assert_event_logged(log_info, action):
    events = event_payloads(log_info, action)

    assert len(events) == 1

    return events[0]


def confirm_profile_from_query(client):
    client.get(
        "/chat",
        params=[
            ("likes", "art"),
            ("location", "Buffalo"),
            ("transportation", "can drive"),
        ],
    )


async def fake_score_jobs(profile, jobs):
    return [
        {
            "id": job["id"],
            "tier": "Moderate",
            "explanation": "Test explanation.",
        }
        for job in jobs
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


def test_chat_stream_logs_assistant_message_received(client):
    user_message = "Paulo"
    assistant_message = "Nice to meet you, Paulo!"

    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        post_response = client.post(
            "/chat",
            data={"message": user_message},
        )

        assert post_response.status_code == 200

        session = current_chat_session(client)

        async def fake_stream_async(message):
            assert message == user_message

            yield {"data": assistant_message}
            yield {"data": ('<profile>{"name":"Paulo","confirmed":false}</profile>')}

            # Make the outer SSE generator close after this response instead
            # of waiting forever for another queued chat message.
            session.active_stream_id = "test-complete"

        session.agent.stream_async = fake_stream_async

        stream_response = client.get("/chat/stream")

    assert stream_response.status_code == 200

    events = event_payloads(
        log_info,
        "assistant_message_received",
    )

    assert len(events) == 1

    event = events[0]

    assert event["message_role"] == "assistant"
    assert event["message_sequence"] == 2
    assert event["message"] == assistant_message
    assert event["character_count"] == len(assistant_message)
    assert event["model"] == server.CHAT_MODEL_NAME

    assert event["first_token_ms"] is not None
    assert event["first_token_ms"] >= 0

    assert event["elapsed_ms"] >= 0


def test_chat_stream_does_not_log_hidden_only_assistant_response(client):
    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        post_response = client.post(
            "/chat",
            data={"message": "Paulo"},
        )

        assert post_response.status_code == 200

        session = current_chat_session(client)

        async def fake_stream_async(message):
            yield {"data": ('<profile>{"name":"Paulo","confirmed":false}</profile>')}

            session.active_stream_id = "test-complete"

        session.agent.stream_async = fake_stream_async

        stream_response = client.get("/chat/stream")

    assert stream_response.status_code == 200

    assistant_events = event_payloads(
        log_info,
        "assistant_message_received",
    )

    assert assistant_events == []

    assert session.chat_message_sequence == 1


def test_chat_reset_logs_event(client):
    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        response = client.post("/chat/reset")

    assert response.status_code == 204
    assert_event_logged(log_info, "chat_reset")


def test_chat_continue_logs_keep_chatting(client):
    confirm_profile_from_query(client)

    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        response = client.post("/chat/continue")

    assert response.status_code == 200
    assert_event_logged(log_info, "keep_chatting")


def test_chat_continue_does_not_log_when_revision_cannot_start(client):
    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        response = client.post("/chat/continue")

    assert response.status_code == 409
    assert event_payloads(log_info, "keep_chatting") == []


def test_chat_profile_logs_edit_profile(client):
    confirm_profile_from_query(client)

    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        response = client.post(
            "/chat/profile",
            json={
                "likes": ["art"],
                "dislikes": [],
                "location": "Buffalo",
                "transportation": "can drive",
                "use_location_matching": True,
            },
        )

    assert response.status_code == 204
    assert_event_logged(log_info, "edit_profile")


def test_chat_reset_preserves_visitor_id(client):
    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        client.post("/chat", data={"message": "Hello"})
        client.post("/chat/reset")
        client.post("/chat", data={"message": "Hello again"})

    user_events = event_payloads(log_info, "user_message_sent")
    reset_event = assert_event_logged(log_info, "chat_reset")

    assert user_events[0]["visitor_id"] == reset_event["visitor_id"]
    assert user_events[1]["visitor_id"] == reset_event["visitor_id"]


def test_ranking_completion_logs_event(client, monkeypatch):
    monkeypatch.setattr(server, "_score_jobs", fake_score_jobs)

    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        with client.stream(
            "GET",
            "/api/rank-opportunities",
            params={"likes": "hands-on work"},
        ) as response:
            assert response.status_code == 200
            _body = "".join(response.iter_text())

    event = assert_event_logged(log_info, "ranking_completed")

    assert event["model"] == server.SCORING_MODEL_NAME
    assert event["jobs"] > 0
    assert event["batches"] > 0
    assert event["elapsed_ms"] >= 0
    assert event["cached"] is False


def test_ranking_cache_hit_logs_event(client, monkeypatch):
    monkeypatch.setattr(server, "_score_jobs", fake_score_jobs)

    params = {"likes": "hands-on work"}

    # Populate the session cache.
    with client.stream(
        "GET",
        "/api/rank-opportunities",
        params=params,
    ) as response:
        assert response.status_code == 200
        _body = "".join(response.iter_text())

    with patch("naswa_matcher.app_logging.logger.info") as log_info:
        with client.stream(
            "GET",
            "/api/rank-opportunities",
            params=params,
        ) as response:
            assert response.status_code == 200
            _body = "".join(response.iter_text())

    event = assert_event_logged(log_info, "ranking_cache_hit")

    assert event["model"] == server.SCORING_MODEL_NAME
    assert event["jobs"] > 0
    assert event["cached"] is True
    assert event["original_elapsed_seconds"] >= 0
