from starlette.responses import Response

from naswa_matcher.ranking_cache import RankingCacheEntry
from naswa_matcher.sessions import (
    INITIAL_CHAT_MESSAGE,
    PREFILLED_PROFILE_MESSAGE,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    ChatMessage,
    ChatSession,
    SessionStore,
    set_session_cookie,
)


def agent_factory_with_history():
    created_agents = []

    def factory():
        agent = object()
        created_agents.append(agent)
        return agent

    return factory, created_agents


def test_session_store_creates_session_when_session_id_is_missing():
    agent_factory, created_agents = agent_factory_with_history()

    store = SessionStore(
        max_age_seconds=100,
        chat_agent_factory=agent_factory,
        clock=lambda: 50.0,
        session_id_factory=lambda: "new-session",
    )

    session_id, session, needs_cookie = store.get_or_create(None)

    assert session_id == "new-session"
    assert needs_cookie is True
    assert session.agent is created_agents[0]
    assert session.last_seen == 50.0
    assert session.messages == [
        ChatMessage(
            role="assistant",
            content=INITIAL_CHAT_MESSAGE,
        )
    ]


def test_session_store_returns_existing_session():
    now = [50.0]
    agent_factory, _created_agents = agent_factory_with_history()

    store = SessionStore(
        max_age_seconds=100,
        chat_agent_factory=agent_factory,
        clock=lambda: now[0],
        session_id_factory=lambda: "existing-session",
    )

    session_id, original_session, _needs_cookie = store.get_or_create(None)

    now[0] = 75.0
    returned_id, returned_session, needs_cookie = store.get_or_create(session_id)

    assert returned_id == session_id
    assert returned_session is original_session
    assert returned_session.last_seen == 75.0
    assert needs_cookie is False


def test_session_store_replaces_expired_session():
    now = [100.0]
    generated_ids = iter(["first-session", "replacement-session"])
    agent_factory, _created_agents = agent_factory_with_history()

    store = SessionStore(
        max_age_seconds=10,
        chat_agent_factory=agent_factory,
        clock=lambda: now[0],
        session_id_factory=lambda: next(generated_ids),
    )

    first_id, first_session, _needs_cookie = store.get_or_create(None)

    now[0] = 111.0
    replacement_id, replacement_session, needs_cookie = store.get_or_create(first_id)

    assert replacement_id == "replacement-session"
    assert replacement_session is not first_session
    assert needs_cookie is True


def test_session_reset_restores_fresh_state():
    agent_factory, created_agents = agent_factory_with_history()
    session = ChatSession(agent_factory=agent_factory)

    original_agent = session.agent
    original_queue = session.queue

    session.profile = {"likes": ["math"], "confirmed": True}
    session.messages.append(ChatMessage(role="user", content="I like math."))
    session.queue.put_nowait("stale message")
    session.active_stream_id = "active-stream"
    session.last_logged_location = "Buffalo"
    session.ranking_cache.entries["cache-key"] = RankingCacheEntry(profile={})

    session.reset()

    assert session.agent is not original_agent
    assert session.agent is created_agents[-1]
    assert session.queue is not original_queue
    assert session.queue.empty()
    assert session.profile is None
    assert session.messages == [
        ChatMessage(
            role="assistant",
            content=INITIAL_CHAT_MESSAGE,
        )
    ]
    assert session.active_stream_id is None
    assert session.ranking_cache.entries == {}
    assert session.last_logged_location is None


def test_apply_confirmed_profile_replaces_initial_transcript():
    agent_factory, _created_agents = agent_factory_with_history()
    session = ChatSession(agent_factory=agent_factory)

    original_agent = session.agent
    original_queue = session.queue

    session.ranking_cache.entries["cache-key"] = RankingCacheEntry(profile={})
    session.active_stream_id = "active-stream"
    session.last_logged_location = "Albany"

    profile = {
        "name": None,
        "likes": ["electronics"],
        "dislikes": [],
        "location": "Buffalo",
        "transportation": "car",
        "use_location_matching": True,
        "confirmed": True,
    }

    session.apply_confirmed_profile(profile)

    assert session.profile is profile
    assert session.agent is not original_agent
    assert session.queue is not original_queue
    assert session.queue.empty()
    assert session.messages == [
        ChatMessage(
            role="assistant",
            content=PREFILLED_PROFILE_MESSAGE,
        )
    ]
    assert session.active_stream_id is None
    assert session.ranking_cache.entries == {}
    assert session.last_logged_location is None


def test_apply_confirmed_profile_preserves_real_conversation():
    agent_factory, _created_agents = agent_factory_with_history()
    session = ChatSession(agent_factory=agent_factory)

    session.messages.extend(
        [
            ChatMessage(role="user", content="My name is Taylor."),
            ChatMessage(role="assistant", content="What kinds of work do you like?"),
        ]
    )

    original_agent = session.agent
    original_messages = list(session.messages)
    original_queue = session.queue

    profile = {
        "name": "Taylor",
        "likes": ["working with tools"],
        "dislikes": [],
        "location": "Buffalo",
        "transportation": "public transit",
        "use_location_matching": True,
        "confirmed": True,
    }

    session.apply_confirmed_profile(profile)

    assert session.profile is profile
    assert session.agent is original_agent
    assert session.messages == original_messages
    assert session.queue is not original_queue


def test_has_user_messages_detects_user_participation():
    agent_factory, _created_agents = agent_factory_with_history()
    session = ChatSession(agent_factory=agent_factory)

    assert session.has_user_messages() is False

    session.messages.append(ChatMessage(role="user", content="Hello"))

    assert session.has_user_messages() is True


def test_set_session_cookie_uses_expected_settings(monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    response = Response()

    set_session_cookie(response, "session-123")

    cookie = response.headers["set-cookie"]

    assert f"{SESSION_COOKIE_NAME}=session-123" in cookie
    assert f"Max-Age={SESSION_MAX_AGE_SECONDS}" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie


def test_set_session_cookie_is_secure_when_configured(monkeypatch):
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    response = Response()

    set_session_cookie(response, "session-123")

    assert "Secure" in response.headers["set-cookie"]
