import asyncio
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from strands import Agent
from strands.models import BedrockModel

from naswa_matcher.db import all_opportunities, get_opportunity
from naswa_matcher.db import load as load_db
from naswa_matcher.location_matching import (
    log_user_location_inference,
    should_use_location_matching,
)
from naswa_matcher.opportunity_detail import build_opportunity_detail
from naswa_matcher.opportunity_stats import sum_openings
from naswa_matcher.profile import (
    build_profile,
    extract_profile,
    has_profile_query_params,
    profile_chat_url,
    profile_rank_params,
    profile_rank_url,
    strip_profile,
)
from naswa_matcher.ranking import build_ranked_items, score_jobs, sort_ranked_items
from naswa_matcher.template_filters import TEMPLATE_FILTERS

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# ── Jinja2 setup ────────────────────────────────────────────────────────────────

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters.update(TEMPLATE_FILTERS)


def render(name: str, **ctx) -> str:
    """Render a template fragment to string (no Request needed)."""
    return templates.env.get_template(name).render(**ctx)


# ── HTML/SSE fragment helpers ────────────────────────────────────────────────


def _render_rank_count(
    *,
    completed_jobs: int,
    total_jobs: int,
    completed_openings: int,
) -> str:
    opportunity_label = "opportunity" if total_jobs == 1 else "opportunities"
    opening_label = "opening" if completed_openings == 1 else "openings"

    return (
        f'<span id="ranked-count" class="ranked-count">{completed_jobs}</span> of {total_jobs} '
        f"{opportunity_label} analyzed "
        f'<span aria-hidden="true"> · </span>'
        f'<span id="openings-count">{completed_openings}</span> {opening_label}'
    )


# ── Logging setup and filters ───────────────────────────────────────────────────

ROOT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
NASWA_LOG_LEVEL = os.getenv("NASWA_LOG_LEVEL", ROOT_LOG_LEVEL).upper()
BOTO_LOG_LEVEL = os.getenv(
    "BOTO_LOG_LEVEL",
    "DEBUG" if ROOT_LOG_LEVEL == "DEBUG" else "WARNING",
).upper()

logging.basicConfig(
    level=getattr(logging, ROOT_LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger("naswa")
logger.setLevel(getattr(logging, NASWA_LOG_LEVEL, logging.INFO))

logging.getLogger("botocore").setLevel(
    getattr(logging, BOTO_LOG_LEVEL, logging.WARNING)
)


def _describe_exception(exc: Exception) -> str:
    """Return a compact message for logs and local/demo UI errors."""
    response = getattr(exc, "response", None)

    if isinstance(response, dict):
        error = response.get("Error", {})
        code = error.get("Code", exc.__class__.__name__)
        message = error.get("Message", str(exc))
        return f"{code}: {message}"

    return f"{exc.__class__.__name__}: {exc}"


# ── Agent setup ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a friendly guide helping a user discover registered apprenticeships that may fit them.

The user has already been greeted and asked for their name.

Your job is to conduct a short, natural conversation and build a hidden profile
that can be used to match the user to apprenticeship opportunities.

The visible conversation should feel like a real conversation, not a form.
However, behind the scenes, you must collect useful profile information.

PROFILE SCHEMA

After every assistant response, output a hidden profile tag on a new line:

<profile>{
  "name": string or null,
  "likes": array of short strings,
  "dislikes": array of short strings,
  "location": string or null,
  "transportation": string or null,
  "use_location_matching": boolean,
  "confirmed": boolean
}</profile>

Rules for the profile:
- The profile is a derived summary, not a raw transcript.
- Do not store long raw user sentences.
- Use short, plain-language phrases.
- Put hobbies, interests, school subjects, strengths, and appealing work activities in "likes".
- Put disliked subjects, disliked activities, and strong avoidances in "dislikes".
- If the user metions an interest that is an academic subject, treat it as a useful like. Do not ask the same thing again as a school question.
- Set use_location_matching to true by default.
- Set use_location_matching to false if the user says they are open to opportunities anywhere in New York State, statewide, willing to relocate, or able to move for the right job.
- If the user gives a specific location and also says they can look statewide or relocate, keep the specific location and set use_location_matching to false.
- Infer values from any answer, even if the user answered a later question early.
- If something is unknown, use null for strings or [] for arrays.
- All profile fields are optional except confirmed.

CONVERSATION STRATEGY

Ask one natural question at a time.

Do not visibly explain your reasoning after each answer.
Bad: "That gives me a good starting point: troubleshooting, electronics, and math."
Good: "Nice. Where would you be looking for work?"

Collect this information when possible:
1. Name
2. Likes / interests / strengths / hobbies / appealing work
3. School subjects they enjoyed, if not already mentioned
3. Location where they are looking for work
4. Transportation or ability to get to job sites/classes

Do not ask a question if the user already answered it earlier.

LOCATION QUESTION STYLE

Ask about where they are looking for work, not where they live.
Use examples:
"Where would you be looking for work? For example, Buffalo and the surrounding area, near Albany, or anywhere in New York."

If the user gives a full street address, ignore the street address and only retain the city, ZIP, county, or region.
If the user gives a location outside New York State, politely explain that this prototype is focused on New York State opportunities and ask if there is anywhere in New York they would consider.

TRANSPORTATION QUESTION STYLE

Ask practically and gently:
"How would you usually get to job sites or classes — driving yourself, public transit, rides from family, or something else?"

Do not make the user feel screened out.

CONFIRMATION

When you have enough information, summarize the profile briefly and ask if it looks right.

Example:
"Great — I’ll use this to look for matches: you like fixing electronics, math, and hands-on problem solving; you’re looking around Buffalo; and you’d mostly use transit or rides. Does that sound right?"

If use_location_matching is false, briefly reflect that back without making it sound like a problem.
Example:
"Great — I’ll use this to look for matches: you like fixing electronics, math, and hands-on problem solving; you’re looking around Buffalo but are open to opportunities anywhere in New York State. Does that sound right?"

Then output the profile with confirmed=false.

If the user confirms, respond briefly:
"Great, I have enough to show matches."

Then output the same profile with confirmed=true.

If the user corrects something, update the profile and continue naturally.

RULES

- Keep responses brief and friendly.
- Only respond to the user's latest actual message.
- Do not invent, assume, simulate, or write future user responses.
- Never write text like "User's response:".
- Output exactly one assistant turn per user message.
- Never mention, explain, or draw attention to the <profile> tag.
- Do not output anything after the <profile> tag.
"""

REQUESTED_MAX_OUTPUT_TOKENS = 16_384


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    max_output_tokens: int
    temperature: float = 0.0


MODEL_CONFIGS = {
    "sonnet-4.6": ModelConfig(
        model_id="us.anthropic.claude-sonnet-4-6",
        max_output_tokens=REQUESTED_MAX_OUTPUT_TOKENS,
    ),
    "nova-lite": ModelConfig(
        model_id="us.amazon.nova-lite-v1:0",
        # Nova Lite v1 max output is 10K, so don't send 16K here.
        max_output_tokens=10_000,
    ),
    "nova-2-lite": ModelConfig(
        model_id="us.amazon.nova-2-lite-v1:0",
        max_output_tokens=REQUESTED_MAX_OUTPUT_TOKENS,
    ),
}


# change model name here
CHAT_MODEL_NAME = os.getenv("CHAT_MODEL_NAME", "sonnet-4.6")
SCORING_MODEL_NAME = os.getenv("SCORING_MODEL_NAME", "nova-2-lite")


def make_bedrock_model(
    model_name: str,
    *,
    streaming: bool = True,
    temperature: float | None = None,
) -> BedrockModel:
    """Create a configured Bedrock model for Strands.

    Supported model_name values:
    - sonnet-4.6
    - nova-lite
    - nova-2-lite
    """
    config = MODEL_CONFIGS[model_name]

    return BedrockModel(
        model_id=config.model_id,
        max_tokens=config.max_output_tokens,
        temperature=config.temperature if temperature is None else temperature,
        streaming=streaming,
    )


def make_agent() -> Agent:
    """Create a fresh agent instance with the guided conversation prompt."""
    return Agent(
        model=make_bedrock_model(CHAT_MODEL_NAME, streaming=True),
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )


def make_scoring_model() -> BedrockModel:
    """Create the non-streaming model used for opportunity scoring."""
    return make_bedrock_model(SCORING_MODEL_NAME, streaming=False)


# ── Session state ─────────────────────────────────────────────────────────────

SESSION_COOKIE_NAME = "tyler_demo_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7 days

INITIAL_CHAT_MESSAGE = (
    "Registered apprenticeships let you earn while you learn. "
    "Let’s see if one might be right for you. What’s your name?"
)


@dataclass
class ChatMessage:
    role: str
    content: str


def _initial_messages() -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            content=INITIAL_CHAT_MESSAGE,
        )
    ]


@dataclass
class RankingCacheEntry:
    """Cached ranked opportunities for one profile inside one browser session."""

    profile: dict
    ranked: list[dict] = field(default_factory=list)
    completed_jobs: int = 0
    total_jobs: int = 0
    completed_openings: int = 0
    total_openings: int = 0
    elapsed_seconds: int = 0
    created_at: float = field(default_factory=time.time)
    is_complete: bool = False


@dataclass
class ChatSession:
    """Ephemeral browser session for the internal demo."""

    agent: Agent = field(default_factory=make_agent)
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    profile: dict | None = None
    messages: list[ChatMessage] = field(default_factory=_initial_messages)
    last_seen: float = field(default_factory=time.time)
    active_stream_id: str | None = None
    ranking_cache: dict[str, RankingCacheEntry] = field(default_factory=dict)
    last_logged_location: str | None = None


_sessions: dict[str, ChatSession] = {}


def _new_session_id() -> str:
    """Create a browser-safe random session ID."""
    return secrets.token_urlsafe(32)


def _cleanup_sessions() -> None:
    """Remove old in-memory sessions so the demo does not leak memory forever."""
    now = time.time()
    expired_session_ids = [
        session_id
        for session_id, session in _sessions.items()
        if now - session.last_seen > SESSION_MAX_AGE_SECONDS
    ]

    for session_id in expired_session_ids:
        del _sessions[session_id]


def _get_or_create_session(request: Request) -> tuple[str, ChatSession, bool]:
    """
    Return the current browser session.

    The bool indicates whether a new cookie needs to be set on the response.
    """
    _cleanup_sessions()

    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    needs_cookie = False

    if not session_id or session_id not in _sessions:
        session_id = _new_session_id()
        _sessions[session_id] = ChatSession()
        needs_cookie = True

    session = _sessions[session_id]
    session.last_seen = time.time()

    return session_id, session, needs_cookie


def _set_session_cookie(response, session_id: str) -> None:
    """Attach the demo session cookie to a response."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,  # TODO: Set to True when serving over HTTPS.
        path="/",
    )


# ── Ranking cache helpers ────────────────────────────────────────────────────

RANKING_CACHE_VERSION = "rank-cache-v1"


def _normalized_profile_for_cache(profile: dict) -> dict:
    """Return a stable, compact profile shape for ranking-cache keys."""

    def clean_list(values) -> list[str]:
        if not isinstance(values, list):
            return []

        cleaned = []
        for value in values:
            text = str(value).strip()
            if text:
                cleaned.append(text)
        return cleaned

    def clean_string(value) -> str | None:
        if value is None:
            return None

        text = str(value).strip()
        return text or None

    return {
        "likes": clean_list(profile.get("likes", [])),
        "dislikes": clean_list(profile.get("dislikes", [])),
        "location": clean_string(profile.get("location")),
        "transportation": clean_string(profile.get("transportation")),
        "use_location_matching": should_use_location_matching(profile),
    }


def _ranking_cache_key(profile: dict) -> str:
    """Build a deterministic cache key for one ranked-opportunities request."""
    return json.dumps(
        {
            "version": RANKING_CACHE_VERSION,
            "profile": _normalized_profile_for_cache(profile),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _get_ranking_cache_entry(
    session: ChatSession,
    cache_key: str,
) -> RankingCacheEntry | None:
    """Return a complete, unexpired ranking cache entry if available."""
    entry = session.ranking_cache.get(cache_key)

    if entry is None:
        return None

    if time.time() - entry.created_at > SESSION_MAX_AGE_SECONDS:
        del session.ranking_cache[cache_key]
        return None

    if not entry.is_complete:
        return None

    return entry


# ── Ranking orchestration helpers ────────────────────────────────────────────

RANKING_BATCH_SIZE = int(os.getenv("RANKING_BATCH_SIZE", "10"))
RANKING_MAX_CONCURRENCY = int(os.getenv("RANKING_MAX_CONCURRENCY", "3"))
RANKING_MAX_ATTEMPTS = int(os.getenv("RANKING_MAX_ATTEMPTS", "3"))
RANKING_RETRY_DELAY_SECONDS = float(os.getenv("RANKING_RETRY_DELAY_SECONDS", "1"))


def _chunks(items: list[dict], size: int) -> list[list[dict]]:
    """Split a list into fixed-size chunks."""
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _score_jobs(profile: dict, onet_jobs: list[dict]) -> list[dict]:
    """Score jobs using the configured scoring model.

    Kept as a thin wrapper so route tests can still monkeypatch this boundary.
    """
    return await score_jobs(
        profile,
        onet_jobs,
        model_factory=make_scoring_model,
    )


# ── App setup ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_db()
    logger.info("Application started and opportunity data loaded")
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


# ── AWS Healthcheck ───────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Landing page ──────────────────────────────────────────────────────────────


@app.get("/")
async def index(request: Request):
    """Serve the public landing page."""
    return templates.TemplateResponse(request, "index.html")


# ── AI disclosure page ───────────────────────────────────────────────────────


@app.get("/ai-disclosure")
async def ai_disclosure(request: Request):
    """Serve the AI disclosure page."""
    return templates.TemplateResponse(request, "ai_disclosure.html")


# ── Chat ──────────────────────────────────────────────────────────────────────


def _has_prior_user_messages(session: ChatSession) -> bool:
    """Return whether the user has already participated in this chat session."""
    return any(message.role == "user" for message in session.messages)


@app.get("/chat")
async def chat_page(
    request: Request,
    likes: list[str] = Query(default=[]),
    dislikes: list[str] = Query(default=[]),
    location: str | None = None,
    transportation: str | None = None,
    use_location_matching: bool | None = None,
):
    """Serve the guided chat page."""
    session_id, session, needs_cookie = _get_or_create_session(request)

    has_prefilled_profile = has_profile_query_params(
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching,
    )

    if has_prefilled_profile:
        profile = build_profile(
            likes=likes,
            dislikes=dislikes,
            location=location,
            transportation=transportation,
            use_location_matching=(
                True if use_location_matching is None else use_location_matching
            ),
            confirmed=True,
        )

        has_prior_user_messages = _has_prior_user_messages(session)

        # Always update the session profile from query params.
        # This lets /opportunities link back to /chat with the edited profile.
        session.profile = profile
        session.ranking_cache.clear()
        session.queue = asyncio.Queue()

        # Only replace the transcript for preloaded/demo links where the user
        # has not actually had a conversation yet.
        if not has_prior_user_messages:
            session.agent = make_agent()
            session.messages = [
                ChatMessage(
                    role="assistant",
                    content=(
                        "Here’s the profile I’ll use to suggest matches. "
                        "You can edit it before seeing jobs."
                    ),
                )
            ]

    ranked_url = None
    if session.profile and session.profile.get("confirmed"):
        ranked_url = profile_rank_url(session.profile)

    response = templates.TemplateResponse(
        request,
        "chat.html",
        {
            "profile": session.profile,
            "messages": session.messages,
            "ranked_url": ranked_url,
        },
    )

    if needs_cookie:
        _set_session_cookie(response, session_id)

    return response


@app.post("/chat/reset")
async def reset_chat(request: Request):
    """Replace this browser session's agent and redirect to a fresh chat page."""
    session_id, session, needs_cookie = _get_or_create_session(request)

    session.agent = make_agent()
    session.profile = None
    session.messages = _initial_messages()
    session.ranking_cache.clear()

    # Replace the queue entirely
    session.queue = asyncio.Queue()

    response = Response(status_code=204)
    response.headers["HX-Redirect"] = "/chat"

    if needs_cookie:
        _set_session_cookie(response, session_id)

    return response


@app.post("/chat")
async def chat(request: Request, message: str = Form(...)):
    """Accept a user message, enqueue it for this browser, return user bubble HTML."""
    session_id, session, needs_cookie = _get_or_create_session(request)

    await session.queue.put(message)
    session.messages.append(ChatMessage(role="user", content=message))
    logger.debug("Chat message queued")

    response = templates.TemplateResponse(
        request, "_message.html", {"role": "user", "content": message}
    )

    if needs_cookie:
        _set_session_cookie(response, session_id)

    return response


@app.get("/chat/stream")
async def chat_stream(request: Request):
    """SSE endpoint: waits for this browser's messages and streams agent tokens."""
    session_id, session, needs_cookie = _get_or_create_session(request)

    stream_queue = session.queue
    stream_id = secrets.token_urlsafe(16)
    session.active_stream_id = stream_id

    async def generate():
        while True:
            # If another EventSource connection replaced this one, stop this generator.
            if session.active_stream_id != stream_id:
                logger.debug("Closing stale chat stream")
                return

            message = await stream_queue.get()

            # If this stream became stale while waiting, put the message back
            # so the active stream can consume it.
            if session.active_stream_id != stream_id:
                await stream_queue.put(message)
                logger.debug("Stale chat stream re-queued message and closed")
                return

            full_text = ""
            prev_display_len = 0

            try:
                logger.debug("Chat agent started")

                async for event in session.agent.stream_async(message):
                    if "data" not in event:
                        continue

                    full_text += event["data"]
                    display = strip_profile(full_text)
                    new_chunk = display[prev_display_len:]

                    if new_chunk:
                        yield {"event": "token", "data": new_chunk}
                        prev_display_len = len(display)

            except Exception as exc:
                error_message = _describe_exception(exc)
                logger.exception("Chat agent failed: %s", error_message)

                msg_html = render(
                    "_message.html",
                    role="assistant",
                    content=(
                        "Sorry, the AI service is not available right now.\n\n"
                        f"Error: {error_message}"
                    ),
                )

                yield {"event": "clear-stream", "data": ""}
                yield {"event": "assistant-message", "data": msg_html}
                continue

            logger.debug("Chat agent completed")

            profile = extract_profile(full_text)
            final_text = strip_profile(full_text)

            yield {"event": "clear-stream", "data": ""}

            if final_text:
                session.messages.append(
                    ChatMessage(role="assistant", content=final_text)
                )
                msg_html = render("_message.html", role="assistant", content=final_text)
                logger.debug("Sending assistant message event")
                yield {"event": "assistant-message", "data": msg_html}

            if profile:
                session.profile = profile

                profile_location = profile.get("location")
                if (
                    profile_location
                    and profile_location != session.last_logged_location
                ):
                    log_user_location_inference(profile_location)
                    session.last_logged_location = profile_location

                if profile.get("confirmed"):
                    ranked_url = profile_rank_url(profile)
                    card_html = render(
                        "_profile_card.html", profile=profile, ranked_url=ranked_url
                    )
                    yield {"event": "profile-confirmed", "data": card_html}

    response = EventSourceResponse(generate())

    if needs_cookie:
        _set_session_cookie(response, session_id)

    return response


# ── Opportunities page ────────────────────────────────────────────────────────


@app.get("/opportunities")
async def opportunities_page(
    request: Request,
    ranked: bool = False,
    likes: list[str] = Query(default=[]),
    dislikes: list[str] = Query(default=[]),
    location: str | None = None,
    transportation: str | None = None,
    use_location_matching: bool = True,
):
    """Serve the opportunities list, optionally in ranked mode."""
    profile = build_profile(
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching,
    )

    if ranked and likes:
        session_id, session, needs_cookie = _get_or_create_session(request)

        session.profile = build_profile(
            name=session.profile.get("name") if session.profile else None,
            likes=likes,
            dislikes=dislikes,
            location=location,
            transportation=transportation,
            use_location_matching=use_location_matching,
            confirmed=True,
        )

        all_jobs = all_opportunities()
        onet_jobs = [j for j in all_jobs if j.get("onet") is not None]
        no_onet_jobs = [j for j in all_jobs if j.get("onet") is None]
        total_openings = sum_openings(onet_jobs)

        cache_key = _ranking_cache_key(profile)
        cached = _get_ranking_cache_entry(session, cache_key)
        ranking_cached = cached is not None
        cached_ranked = cached.ranked if cached else []

        rank_stream_url = "/api/rank-opportunities?" + urlencode(
            profile_rank_params(profile)
        )

        unranked = [{"id": j["id"], "posting": j["posting"]} for j in no_onet_jobs]

        response = templates.TemplateResponse(
            request,
            "opportunities.html",
            {
                "ranked": True,
                "rank_stream_url": rank_stream_url,
                "profile": profile,
                "chat_profile_url": profile_chat_url(profile),
                "likes": likes,
                "ranked_total": len(onet_jobs),
                "unranked": unranked,
                "completed_jobs": cached.completed_jobs if cached else 0,
                "total_jobs": cached.total_jobs if cached else len(onet_jobs),
                "completed_openings": cached.completed_openings if cached else 0,
                "total_openings": cached.total_openings if cached else total_openings,
                "is_done": ranking_cached,
                "ranking_cached": ranking_cached,
                "cached_ranked": cached_ranked,
                "cached_elapsed_seconds": cached.elapsed_seconds if cached else 0,
            },
        )

        if needs_cookie:
            _set_session_cookie(response, session_id)

        return response

    return templates.TemplateResponse(
        request,
        "opportunities.html",
        {"ranked": False, "opportunities": all_opportunities()},
    )


# ── Single opportunity page ───────────────────────────────────────────────────


@app.get("/opportunities/{slug}")
async def opportunity_detail_page(request: Request, slug: str):
    """Serve the opportunity detail page."""
    opp = get_opportunity(slug)
    if opp is None:
        raise HTTPException(status_code=404)

    detail = build_opportunity_detail(opp)

    return templates.TemplateResponse(
        request,
        "opportunity.html",
        {
            "opp": opp,
            "detail": detail,
        },
    )


# ── Ranking ───────────────────────────────────────────────────────────────────


@app.get("/api/rank-opportunities")
async def rank_opportunities_stream(
    request: Request,
    likes: list[str] = Query(default=[]),
    dislikes: list[str] = Query(default=[]),
    location: str | None = None,
    transportation: str | None = None,
    use_location_matching: bool = True,
):
    """
    Rank ONET jobs in parallel batches and stream result cards as each batch completes.

    Completed rankings are cached inside the user's browser session so returning
    to the same ranked opportunities URL does not rerun the AI scoring work.
    """
    session_id, session, needs_cookie = _get_or_create_session(request)

    profile = profile = build_profile(
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching,
    )

    cache_key = _ranking_cache_key(profile)
    cached = _get_ranking_cache_entry(session, cache_key)

    if cached:
        benchmark_id = secrets.token_hex(4)

        logger.info(
            "Streaming opportunity ranking cache hit id=%s jobs=%s elapsed_seconds=%s",
            benchmark_id,
            len(cached.ranked),
            cached.elapsed_seconds,
        )

        async def generate_cached():
            cards_html = render(
                "_rank_cards.html",
                ranked=cached.ranked,
            )

            if cards_html.strip():
                yield {
                    "event": "batch",
                    "data": cards_html,
                }

            progress_html = render(
                "_rank_progress.html",
                completed_jobs=cached.completed_jobs,
                total_jobs=cached.total_jobs,
                completed_openings=cached.completed_openings,
                total_openings=cached.total_openings,
                is_done=True,
            )

            yield {
                "event": "progress",
                "data": progress_html,
            }

            yield {
                "event": "rank-count",
                "data": _render_rank_count(
                    completed_jobs=cached.completed_jobs,
                    total_jobs=cached.total_jobs,
                    completed_openings=cached.completed_openings,
                ),
            }

            yield {
                "event": "done",
                "data": str(cached.elapsed_seconds),
            }

        response = EventSourceResponse(generate_cached())

        if needs_cookie:
            _set_session_cookie(response, session_id)

        return response

    benchmark_id = secrets.token_hex(4)
    request_started_at = time.perf_counter()

    all_jobs = all_opportunities()
    onet_jobs = [j for j in all_jobs if j.get("onet") is not None]
    total_openings = sum_openings(onet_jobs)

    job_index = {job["id"]: index for index, job in enumerate(onet_jobs)}
    batches = _chunks(onet_jobs, RANKING_BATCH_SIZE)
    total_batches = len(batches)

    logger.info(
        "Streaming opportunity ranking started id=%s model=%s jobs=%s batches=%s batch_size=%s concurrency=%s",
        benchmark_id,
        SCORING_MODEL_NAME,
        len(onet_jobs),
        total_batches,
        RANKING_BATCH_SIZE,
        RANKING_MAX_CONCURRENCY,
    )

    async def generate():
        semaphore = asyncio.Semaphore(RANKING_MAX_CONCURRENCY)
        completed_batches = 0
        completed_jobs = 0
        completed_openings = 0
        ranked_for_cache: list[dict] = []
        had_batch_error = False
        disconnected = False

        async def rank_batch(batch_number: int, batch_jobs: list[dict]) -> dict:
            async with semaphore:
                batch_started_at = time.perf_counter()

                logger.debug(
                    "Ranking batch started id=%s batch=%s/%s jobs=%s model=%s",
                    benchmark_id,
                    batch_number,
                    total_batches,
                    len(batch_jobs),
                    SCORING_MODEL_NAME,
                )

                try:
                    scores = None

                    for attempt in range(1, RANKING_MAX_ATTEMPTS + 1):
                        try:
                            scores = await _score_jobs(profile, batch_jobs)
                            break

                        except Exception as exc:
                            error_message = _describe_exception(exc)

                            if attempt == RANKING_MAX_ATTEMPTS:
                                raise

                            delay_seconds = RANKING_RETRY_DELAY_SECONDS * attempt

                            logger.warning(
                                "Ranking batch attempt failed; retrying id=%s batch=%s/%s jobs=%s attempt=%s/%s retry_in=%.2fs error=%s",
                                benchmark_id,
                                batch_number,
                                total_batches,
                                len(batch_jobs),
                                attempt,
                                RANKING_MAX_ATTEMPTS,
                                delay_seconds,
                                error_message,
                            )

                            await asyncio.sleep(delay_seconds)

                    if scores is None:
                        raise RuntimeError("Ranking batch did not return scores.")

                    if len(scores) != len(batch_jobs):
                        logger.warning(
                            "Ranking batch returned unexpected score count id=%s batch=%s/%s jobs=%s scores=%s model=%s",
                            benchmark_id,
                            batch_number,
                            total_batches,
                            len(batch_jobs),
                            len(scores),
                            SCORING_MODEL_NAME,
                        )

                    ranked = build_ranked_items(
                        batch_jobs=batch_jobs,
                        scores=scores,
                        job_index=job_index,
                        profile=profile,
                    )

                    elapsed_ms = (time.perf_counter() - batch_started_at) * 1000

                    logger.debug(
                        "Ranking batch completed id=%s batch=%s/%s jobs=%s scores=%s elapsed_ms=%.1f",
                        benchmark_id,
                        batch_number,
                        total_batches,
                        len(batch_jobs),
                        len(scores),
                        elapsed_ms,
                    )

                    return {
                        "batch_number": batch_number,
                        "jobs": batch_jobs,
                        "ranked": ranked,
                        "error": None,
                        "elapsed_ms": elapsed_ms,
                    }

                except Exception as exc:
                    elapsed_ms = (time.perf_counter() - batch_started_at) * 1000
                    error_message = _describe_exception(exc)

                    logger.exception(
                        "Ranking batch failed id=%s batch=%s/%s jobs=%s elapsed_ms=%.1f error=%s",
                        benchmark_id,
                        batch_number,
                        total_batches,
                        len(batch_jobs),
                        elapsed_ms,
                        error_message,
                    )

                    return {
                        "batch_number": batch_number,
                        "jobs": batch_jobs,
                        "ranked": [],
                        "error": error_message,
                        "elapsed_ms": elapsed_ms,
                    }

        tasks = [
            asyncio.create_task(rank_batch(batch_number, batch_jobs))
            for batch_number, batch_jobs in enumerate(batches, start=1)
        ]

        try:
            for task in asyncio.as_completed(tasks):
                if await request.is_disconnected():
                    disconnected = True
                    logger.info(
                        "Streaming opportunity ranking disconnected id=%s completed_batches=%s/%s",
                        benchmark_id,
                        completed_batches,
                        total_batches,
                    )
                    break

                result = await task
                completed_batches += 1
                completed_jobs += len(result["jobs"])
                completed_openings += sum_openings(result["jobs"])

                if result["error"]:
                    had_batch_error = True

                    yield {
                        "event": "batch-error",
                        "data": (
                            f"<p class='empty-state surface surface--shadow'>"
                            f"One ranking batch failed: {result['error']}"
                            f"</p>"
                        ),
                    }
                else:
                    ranked_for_cache.extend(result["ranked"])

                    cards_html = render(
                        "_rank_cards.html",
                        ranked=result["ranked"],
                    )

                    yield {
                        "event": "batch",
                        "data": cards_html,
                    }

                elapsed_seconds = round(time.perf_counter() - request_started_at)

                progress_html = render(
                    "_rank_progress.html",
                    completed_jobs=completed_jobs,
                    total_jobs=len(onet_jobs),
                    completed_openings=completed_openings,
                    total_openings=total_openings,
                    is_done=False,
                    elapsed_seconds=elapsed_seconds,
                )

                yield {
                    "event": "progress",
                    "data": progress_html,
                }

                yield {
                    "event": "rank-count",
                    "data": _render_rank_count(
                        completed_jobs=completed_jobs,
                        total_jobs=len(onet_jobs),
                        completed_openings=completed_openings,
                    ),
                }

            if disconnected:
                return

            total_elapsed_ms = (time.perf_counter() - request_started_at) * 1000
            total_elapsed_seconds = round(total_elapsed_ms / 1000)

            logger.info(
                "Streaming opportunity ranking completed id=%s jobs=%s batches=%s total_elapsed_ms=%.1f",
                benchmark_id,
                len(onet_jobs),
                total_batches,
                total_elapsed_ms,
            )

            final_ranked = sort_ranked_items(ranked_for_cache, profile)

            if completed_jobs == len(onet_jobs) and not had_batch_error:
                session.ranking_cache[cache_key] = RankingCacheEntry(
                    profile=_normalized_profile_for_cache(profile),
                    ranked=final_ranked,
                    completed_jobs=completed_jobs,
                    total_jobs=len(onet_jobs),
                    completed_openings=completed_openings,
                    total_openings=total_openings,
                    elapsed_seconds=total_elapsed_seconds,
                    is_complete=True,
                )

                logger.info(
                    "Opportunity ranking cached id=%s jobs=%s elapsed_seconds=%s",
                    benchmark_id,
                    len(final_ranked),
                    total_elapsed_seconds,
                )

            final_progress_html = render(
                "_rank_progress.html",
                completed_jobs=completed_jobs,
                total_jobs=len(onet_jobs),
                completed_openings=completed_openings,
                total_openings=total_openings,
                is_done=True,
            )

            yield {
                "event": "progress",
                "data": final_progress_html,
            }

            yield {
                "event": "rank-count",
                "data": _render_rank_count(
                    completed_jobs=completed_jobs,
                    total_jobs=len(onet_jobs),
                    completed_openings=completed_openings,
                ),
            }

            yield {
                "event": "done",
                "data": str(total_elapsed_seconds),
            }

        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    response = EventSourceResponse(generate())

    if needs_cookie:
        _set_session_cookie(response, session_id)

    return response
