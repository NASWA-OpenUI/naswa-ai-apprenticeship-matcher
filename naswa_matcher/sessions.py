import asyncio
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from starlette.responses import Response
from strands import Agent

from naswa_matcher.ranking_cache import RankingCache

SESSION_COOKIE_NAME = "tyler_session_cookie"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7 days

_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
_FALSE_ENV_VALUES = {"0", "false", "no", "off"}


def _session_cookie_secure() -> bool:
    """Return whether cookies should be restricted to HTTPS connections."""
    value = os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower()

    if value in _TRUE_ENV_VALUES:
        return True

    if value in _FALSE_ENV_VALUES:
        return False

    raise ValueError(
        "SESSION_COOKIE_SECURE must be one of: "
        "true, false, 1, 0, yes, no, on, or off."
    )


def _new_ranking_cache() -> RankingCache:
    """Create a ranking cache with the same lifetime as its browser session."""
    return RankingCache(
        max_age_seconds=SESSION_MAX_AGE_SECONDS,
    )


INITIAL_CHAT_MESSAGE = (
    "Registered apprenticeships let you earn while you learn. "
    "Let’s see if one might be right for you. What’s your name?"
)

PREFILLED_PROFILE_MESSAGE = (
    "Here’s the profile I’ll use to suggest matches. "
    "You can edit it before seeing jobs."
)

AgentFactory = Callable[[], Agent]
Clock = Callable[[], float]
SessionIdFactory = Callable[[], str]


@dataclass
class ChatMessage:
    role: str
    content: str


def initial_messages() -> list[ChatMessage]:
    """Return a fresh initial chat transcript."""
    return [
        ChatMessage(
            role="assistant",
            content=INITIAL_CHAT_MESSAGE,
        )
    ]


@dataclass
class ChatSession:
    """Ephemeral browser session for the internal demo."""

    agent_factory: AgentFactory = field(repr=False, compare=False)
    agent: Agent = field(init=False)
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    profile: dict | None = None
    messages: list[ChatMessage] = field(default_factory=initial_messages)
    last_seen: float = field(default_factory=time.time)
    active_stream_id: str | None = None
    ranking_cache: RankingCache = field(default_factory=_new_ranking_cache)
    last_logged_location: str | None = None

    def __post_init__(self) -> None:
        self.agent = self.agent_factory()

    def has_user_messages(self) -> bool:
        """Return whether the user has participated in this conversation."""
        return any(message.role == "user" for message in self.messages)

    def reset(self) -> None:
        """Restore the session to a fresh chat state."""
        self.agent = self.agent_factory()
        self.queue = asyncio.Queue()
        self.profile = None
        self.messages = initial_messages()
        self.active_stream_id = None
        self.ranking_cache.clear()
        self.last_logged_location = None

    def apply_confirmed_profile(self, profile: dict) -> None:
        """
        Apply a profile loaded from query parameters.

        The initial transcript is replaced for preloaded/demo sessions, but a
        real conversation is preserved when the user has already participated.
        """
        replace_transcript = not self.has_user_messages()

        self.profile = profile
        self.queue = asyncio.Queue()
        self.active_stream_id = None
        self.ranking_cache.clear()
        self.last_logged_location = None

        if replace_transcript:
            self.agent = self.agent_factory()
            self.messages = [
                ChatMessage(
                    role="assistant",
                    content=PREFILLED_PROFILE_MESSAGE,
                )
            ]


def _new_session_id() -> str:
    """Create a browser-safe random session ID."""
    return secrets.token_urlsafe(32)


class SessionStore:
    """Manage the application's in-memory browser sessions."""

    def __init__(
        self,
        *,
        max_age_seconds: int,
        chat_agent_factory: AgentFactory,
        clock: Clock = time.time,
        session_id_factory: SessionIdFactory = _new_session_id,
    ) -> None:
        self.max_age_seconds = max_age_seconds
        self.chat_agent_factory = chat_agent_factory
        self._clock = clock
        self._session_id_factory = session_id_factory
        self._sessions: dict[str, ChatSession] = {}

    def get_or_create(
        self,
        session_id: str | None,
    ) -> tuple[str, ChatSession, bool]:
        """
        Return an existing session or create a new one.

        The boolean indicates whether the caller needs to set a new cookie.
        """
        now = self._clock()
        self._cleanup_expired(now)

        needs_cookie = not session_id or session_id not in self._sessions

        if needs_cookie:
            session_id = self._session_id_factory()
            self._sessions[session_id] = ChatSession(
                agent_factory=self.chat_agent_factory,
                last_seen=now,
            )

        session = self._sessions[session_id]
        session.last_seen = now

        return session_id, session, needs_cookie

    def cleanup(self) -> None:
        """Remove expired sessions."""
        self._cleanup_expired(self._clock())

    def clear(self) -> None:
        """Remove all sessions, primarily for tests and controlled resets."""
        self._sessions.clear()

    def _cleanup_expired(self, now: float) -> None:
        expired_session_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.last_seen > self.max_age_seconds
        ]

        for session_id in expired_session_ids:
            del self._sessions[session_id]


def set_session_cookie(response: Response, session_id: str) -> None:
    """Attach the application session cookie to a response."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_session_cookie_secure(),
        path="/",
    )
