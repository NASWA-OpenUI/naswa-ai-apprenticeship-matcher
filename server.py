import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from naswa_matcher.agents import (
    CHAT_MODEL_NAME,
    SCORING_MODEL_NAME,
    make_chat_agent,
    make_scoring_model,
)
from naswa_matcher.app_logging import (
    configure_logging,
    describe_exception,
    log_event,
    log_exception,
    log_request,
    visitor_id_from_session_id,
)
from naswa_matcher.db import (
    all_opportunities,
    all_program_groups,
    get_opportunity,
    get_program_group,
)
from naswa_matcher.db import load as load_db
from naswa_matcher.location_data import REGION_KEY_TO_NAME
from naswa_matcher.location_matching import location_inference_details
from naswa_matcher.match_target import MATCH_TARGET, MatchTarget
from naswa_matcher.opportunity_detail import build_opportunity_detail
from naswa_matcher.opportunity_stats import sum_openings
from naswa_matcher.profile import (
    build_profile,
    clean_profile_values,
    extract_profile,
    has_profile_query_params,
    profile_chat_url,
    profile_match_url,
    profile_query_params,
    strip_profile,
)
from naswa_matcher.program_ranking import (
    build_ranked_program_items,
    program_group_title,
    score_program_groups,
    sum_programs,
)
from naswa_matcher.ranking import (
    build_ranked_items,
    score_jobs,
)
from naswa_matcher.ranking_stream import (
    RankingStreamAdapter,
    RankingStreamConfig,
    chunk_items,
    stream_cached_ranking,
    stream_ranking,
)
from naswa_matcher.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    ChatMessage,
    SessionStore,
    set_session_cookie,
)
from naswa_matcher.template_filters import TEMPLATE_FILTERS

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

REGION_FILTER_OPTIONS = tuple(REGION_KEY_TO_NAME.values())

# ── Jinja2 setup ────────────────────────────────────────────────────────────────


def get_github_sha() -> str | None:
    """Return the deployed Git commit SHA when supplied by the environment."""
    value = os.getenv("GITHUB_SHA", "").strip()
    return value or None


templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters.update(TEMPLATE_FILTERS)
templates.env.globals["get_github_sha"] = get_github_sha


def render(name: str, **ctx) -> str:
    """Render a template fragment to string (no Request needed)."""
    return templates.env.get_template(name).render(**ctx)


# ── Logging setup and filters ───────────────────────────────────────────────────

ROOT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
NASWA_LOG_LEVEL = os.getenv("NASWA_LOG_LEVEL", ROOT_LOG_LEVEL).upper()
BOTO_LOG_LEVEL = os.getenv(
    "BOTO_LOG_LEVEL",
    "DEBUG" if ROOT_LOG_LEVEL == "DEBUG" else "WARNING",
).upper()

logger = configure_logging(
    root_level=ROOT_LOG_LEVEL,
    logger_levels={
        "naswa": NASWA_LOG_LEVEL,
        "botocore": BOTO_LOG_LEVEL,
    },
    disabled_loggers={
        "uvicorn.access",
    },
)


# ── Session state ─────────────────────────────────────────────────────────────

session_store = SessionStore(
    max_age_seconds=SESSION_MAX_AGE_SECONDS,
    chat_agent_factory=make_chat_agent,
)

# ── Ranking orchestration helpers ────────────────────────────────────────────

RANKING_BATCH_SIZE = int(os.getenv("RANKING_BATCH_SIZE", "10"))
RANKING_MAX_CONCURRENCY = int(os.getenv("RANKING_MAX_CONCURRENCY", "3"))
RANKING_MAX_ATTEMPTS = int(os.getenv("RANKING_MAX_ATTEMPTS", "3"))
RANKING_RETRY_DELAY_SECONDS = float(os.getenv("RANKING_RETRY_DELAY_SECONDS", "1"))

RANKING_STREAM_CONFIG = RankingStreamConfig(
    batch_size=RANKING_BATCH_SIZE,
    max_concurrency=RANKING_MAX_CONCURRENCY,
    max_attempts=RANKING_MAX_ATTEMPTS,
    retry_delay_seconds=RANKING_RETRY_DELAY_SECONDS,
)

OPPORTUNITY_RANKING_ADAPTER = RankingStreamAdapter(
    cards_template="_rank_cards.html",
    item_singular="opportunity",
    item_plural="opportunities",
    unit_singular="opening",
    unit_plural="openings",
    build_ranked_items=build_ranked_items,
    count_units=sum_openings,
)

PROGRAM_RANKING_ADAPTER = RankingStreamAdapter(
    cards_template="_program_rank_cards.html",
    item_singular="career",
    item_plural="careers",
    unit_singular="registered program",
    unit_plural="registered programs",
    build_ranked_items=build_ranked_program_items,
    count_units=sum_programs,
)


async def _score_jobs(profile: dict, onet_jobs: list[dict]) -> list[dict]:
    """Score jobs using the configured scoring model.

    Kept as a thin wrapper so route tests can still monkeypatch this boundary.
    """
    return await score_jobs(
        profile,
        onet_jobs,
        model_factory=make_scoring_model,
    )


async def _score_program_groups(
    profile: dict,
    program_groups: list[dict],
) -> list[dict]:
    """Score program groups using the configured scoring model."""
    return await score_program_groups(
        profile,
        program_groups,
        model_factory=make_scoring_model,
    )


# ── App setup ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_db()
    logger.info("Application started and local data loaded")
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def _should_handle_application_request(request: Request) -> bool:
    """Return whether this request should receive app session/log context."""
    path = request.url.path

    return path != "/health" and not path.startswith("/static/")


def _request_action(request: Request) -> str:
    """Return the high-level action used for request logs."""
    if request.method == "GET" and not request.url.path.startswith(
        ("/api/", "/chat/stream")
    ):
        return "pageview"

    return "request"


@app.middleware("http")
async def application_request_context(request: Request, call_next):
    """Add session, visitor, request, timing, and logging context."""
    if not _should_handle_application_request(request):
        return await call_next(request)

    request_id = str(uuid.uuid4())

    session_id, session = session_store.get_or_create(
        request.cookies.get(SESSION_COOKIE_NAME)
    )

    request.state.request_id = request_id
    request.state.visitor_id = visitor_id_from_session_id(session_id)
    request.state.session_id = session_id
    request.state.session = session

    started_at = time.perf_counter()
    action = _request_action(request)

    try:
        response = await call_next(request)

    except Exception:
        elapsed_ms = (time.perf_counter() - started_at) * 1000

        log_request(
            request,
            action=action,
            status_code=500,
            duration_ms=elapsed_ms,
        )

        raise

    elapsed_ms = (time.perf_counter() - started_at) * 1000

    # Refresh the same seven-day session cookie on every meaningful request.
    set_session_cookie(response, session_id)

    # Useful for correlating a browser/network request with its server logs.
    response.headers["X-Request-ID"] = request_id

    if action == "pageview" or response.status_code >= 400:
        log_request(
            request,
            action=action,
            status_code=response.status_code,
            duration_ms=elapsed_ms,
        )

    return response


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


class ChatProfileUpdate(BaseModel):
    """Profile values submitted from the profile-edit modal."""

    name: str | None = None
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    location: str | None = None
    transportation: str | None = None
    use_location_matching: bool = True


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
    session = request.state.session

    has_prefilled_profile = has_profile_query_params(
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching,
    )

    if has_prefilled_profile:
        profile = build_profile(
            name=session.profile.get("name") if session.profile else None,
            likes=clean_profile_values(likes),
            dislikes=clean_profile_values(dislikes),
            location=(location or "").strip() or None,
            transportation=(transportation or "").strip() or None,
            use_location_matching=(
                True if use_location_matching is None else use_location_matching
            ),
            confirmed=True,
        )

        session.apply_confirmed_profile(profile)

    matches_url = None
    if session.profile and session.profile.get("confirmed"):
        matches_url = profile_match_url(session.profile, MATCH_TARGET)

    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "profile": session.profile,
            "messages": session.messages,
            "matches_url": matches_url,
            "match_target": MATCH_TARGET.value,
        },
    )


@app.post("/chat/reset")
async def reset_chat(request: Request):
    """Reset this browser session and redirect to a fresh chat page."""
    session = request.state.session

    session.reset()

    log_event(request, "chat_reset")

    response = Response(status_code=204)
    response.headers["HX-Redirect"] = "/chat"

    return response


@app.post("/chat/profile")
async def update_chat_profile(
    request: Request,
    update: ChatProfileUpdate,
):
    """Persist a modal-edited profile and synchronize Tyler's hidden context."""
    session = request.state.session

    existing_name = session.profile.get("name") if session.profile else None

    if update.name is None:
        name = existing_name
    else:
        name = update.name.strip() or None

    profile = build_profile(
        name=name,
        likes=clean_profile_values(update.likes),
        dislikes=clean_profile_values(update.dislikes),
        location=(update.location or "").strip() or None,
        transportation=(update.transportation or "").strip() or None,
        use_location_matching=update.use_location_matching,
        confirmed=True,
    )

    session.sync_confirmed_profile(profile)

    log_event(request, "edit_profile")

    return Response(status_code=204)


@app.post("/chat/continue")
async def continue_chat(request: Request):
    """Resume conversation using the session's current profile as context."""
    session = request.state.session

    if not session.begin_profile_revision():
        return Response(status_code=409)

    log_event(request, "keep_chatting")

    content = (
        "Sure — let’s keep chatting. What would you like to change about your profile?"
    )

    session.messages.append(
        ChatMessage(
            role="assistant",
            content=content,
        )
    )

    return templates.TemplateResponse(
        request,
        "_message.html",
        {
            "role": "assistant",
            "content": content,
        },
    )


@app.post("/chat")
async def chat(
    request: Request,
    message: str | None = Form(default=None),
):
    """Accept and enqueue a non-empty user message."""
    message = (message or "").strip()

    if not message:
        return Response(status_code=204)

    session = request.state.session

    sequence = session.next_chat_message_sequence()

    log_event(
        request,
        "user_message_sent",
        message_role="user",
        message_sequence=sequence,
        message=message,
        character_count=len(message),
    )

    await session.queue.put(message)
    session.messages.append(ChatMessage(role="user", content=message))
    logger.debug("Chat message queued")

    return templates.TemplateResponse(
        request, "_message.html", {"role": "user", "content": message}
    )


@app.get("/chat/stream")
async def chat_stream(request: Request):
    """SSE endpoint: waits for this browser's messages and streams agent tokens."""
    session = request.state.session

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
            chat_started_at = time.perf_counter()
            first_token_ms: float | None = None

            try:
                logger.debug("Chat agent started")

                async for event in session.agent.stream_async(message):
                    if "data" not in event:
                        continue

                    full_text += event["data"]
                    display = strip_profile(full_text)
                    new_chunk = display[prev_display_len:]

                    if new_chunk:
                        if first_token_ms is None:
                            first_token_ms = (
                                time.perf_counter() - chat_started_at
                            ) * 1000
                        yield {"event": "token", "data": new_chunk}
                        prev_display_len = len(display)

            except Exception as exc:
                error_message = describe_exception(exc)

                log_exception(
                    request,
                    "chat_agent_failed",
                    error=error_message,
                    model=CHAT_MODEL_NAME,
                )

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

            elapsed_ms = (time.perf_counter() - chat_started_at) * 1000

            logger.debug("Chat agent completed")

            profile = extract_profile(full_text)
            final_text = strip_profile(full_text)

            yield {"event": "clear-stream", "data": ""}

            if final_text:
                session.messages.append(
                    ChatMessage(role="assistant", content=final_text)
                )
                msg_html = render("_message.html", role="assistant", content=final_text)

                log_event(
                    request,
                    "assistant_message_received",
                    message_role="assistant",
                    message_sequence=session.next_chat_message_sequence(),
                    message=final_text,
                    character_count=len(final_text),
                    model=CHAT_MODEL_NAME,
                    first_token_ms=(
                        round(first_token_ms, 1) if first_token_ms is not None else None
                    ),
                    elapsed_ms=round(elapsed_ms, 1),
                )

                logger.debug("Sending assistant message event")

                yield {
                    "event": "assistant-message",
                    "data": msg_html,
                }

            if profile:
                session.profile = profile

                profile_location = profile.get("location")
                if (
                    profile_location
                    and profile_location != session.last_logged_location
                ):
                    log_event(
                        request,
                        "location_inferred",
                        **location_inference_details(profile_location),
                    )
                    session.last_logged_location = profile_location

                if profile.get("confirmed"):
                    log_event(request, "profile_confirmed")

                    matches_url = profile_match_url(profile, MATCH_TARGET)
                    card_html = render(
                        "_profile_card.html",
                        profile=profile,
                        matches_url=matches_url,
                        match_target=MATCH_TARGET.value,
                    )
                    yield {"event": "profile-confirmed", "data": card_html}

    return EventSourceResponse(generate())


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
    """Browse opportunities or serve AI-ranked opportunity matches."""

    if not (ranked and likes):
        return templates.TemplateResponse(
            request,
            "opportunities_browse.html",
            {"opportunities": all_opportunities()},
        )

    profile = build_profile(
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching,
    )

    session = request.state.session

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
    onet_jobs = [job for job in all_jobs if job.get("onet") is not None]
    no_onet_jobs = [job for job in all_jobs if job.get("onet") is None]

    total_openings = sum_openings(onet_jobs)

    cached = session.ranking_cache.get(profile, MatchTarget.OPPORTUNITIES)

    ranking_cached = cached is not None
    cached_ranked = cached.ranked if cached else []

    params = profile_query_params(profile)

    rank_stream_url = "/api/rank-opportunities"
    if params:
        rank_stream_url += "?" + urlencode(params)

    unranked = [
        {
            "id": job["id"],
            "posting": job["posting"],
        }
        for job in no_onet_jobs
    ]

    return templates.TemplateResponse(
        request,
        "opportunities.html",
        {
            "rank_stream_url": rank_stream_url,
            "profile": profile,
            "match_target": MatchTarget.OPPORTUNITIES.value,
            "chat_profile_url": profile_chat_url(profile),
            "likes": likes,
            "unranked": unranked,
            "completed_items": cached.completed_items if cached else 0,
            "total_items": cached.total_items if cached else len(onet_jobs),
            "completed_units": cached.completed_units if cached else 0,
            "total_units": cached.total_units if cached else total_openings,
            "is_done": ranking_cached,
            "ranking_cached": ranking_cached,
            "cached_ranked": cached_ranked,
            "cached_elapsed_seconds": cached.elapsed_seconds if cached else 0,
            "item_singular": "opportunity",
            "item_plural": "opportunities",
            "unit_singular": "opening",
            "unit_plural": "openings",
            "region_filter_options": REGION_FILTER_OPTIONS,
            "show_license_filter": True,
            "filter_item_singular": "opportunity",
            "filter_item_plural": "opportunities",
        },
    )


# ── Single opportunity page ───────────────────────────────────────────────────


@app.get("/opportunities/{slug}")
async def opportunity_detail_page(
    request: Request,
    slug: str,
    from_program: str | None = None,
):
    """Serve the opportunity detail page."""
    opp = get_opportunity(slug)
    if opp is None:
        raise HTTPException(status_code=404)

    detail = build_opportunity_detail(opp)

    back_href = "/opportunities"
    back_label = "← All opportunities"

    if from_program:
        program_group = get_program_group(from_program)

        if program_group is not None:
            back_href = f"/programs/{program_group['socCode']}"
            back_label = "← Back to program details"

    return templates.TemplateResponse(
        request,
        "opportunity.html",
        {
            "opp": opp,
            "detail": detail,
            "back_href": back_href,
            "back_label": back_label,
        },
    )


# ── Opportunity ranking ───────────────────────────────────────────────────────


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
    session = request.state.session

    profile = build_profile(
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching,
    )

    cached = session.ranking_cache.get(profile, MatchTarget.OPPORTUNITIES)

    if cached:
        log_event(
            request,
            "ranking_cache_hit",
            target=MatchTarget.OPPORTUNITIES.value,
            model=SCORING_MODEL_NAME,
            items=len(cached.ranked),
            cached=True,
            original_elapsed_seconds=cached.elapsed_seconds,
        )

        return EventSourceResponse(
            stream_cached_ranking(
                cached,
                render=render,
                adapter=OPPORTUNITY_RANKING_ADAPTER,
            )
        )

    request_started_at = time.perf_counter()

    all_jobs = all_opportunities()
    onet_jobs = [job for job in all_jobs if job.get("onet") is not None]

    total_openings = sum_openings(onet_jobs)

    job_index = {job["id"]: index for index, job in enumerate(onet_jobs)}

    batches = chunk_items(
        onet_jobs,
        RANKING_STREAM_CONFIG.batch_size,
    )
    total_batches = len(batches)

    log_event(
        request,
        "ranking_started",
        target=MatchTarget.OPPORTUNITIES.value,
        model=SCORING_MODEL_NAME,
        items=len(onet_jobs),
        units=total_openings,
        batches=len(batches),
        batch_size=RANKING_STREAM_CONFIG.batch_size,
        concurrency=RANKING_STREAM_CONFIG.max_concurrency,
        cached=False,
    )

    return EventSourceResponse(
        stream_ranking(
            request=request,
            session=session,
            target=MatchTarget.OPPORTUNITIES,
            profile=profile,
            request_started_at=request_started_at,
            items=onet_jobs,
            total_units=total_openings,
            item_index=job_index,
            batches=batches,
            score_items=_score_jobs,
            adapter=OPPORTUNITY_RANKING_ADAPTER,
            render=render,
            config=RANKING_STREAM_CONFIG,
        )
    )


# ── Programs page ─────────────────────────────────────────────────────────────


@app.get("/programs")
async def programs_page(
    request: Request,
    likes: list[str] = Query(default=[]),
    dislikes: list[str] = Query(default=[]),
    location: str | None = None,
    transportation: str | None = None,
    use_location_matching: bool | None = None,
):
    """Browse programs or serve AI-ranked program matches."""
    has_profile = has_profile_query_params(
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching,
    )

    if not has_profile:
        program_groups = all_program_groups()

        return templates.TemplateResponse(
            request,
            "programs_browse.html",
            {
                "program_groups": program_groups,
                "total_items": len(program_groups),
                "total_units": sum_programs(program_groups),
            },
        )

    use_location_matching_value = (
        True if use_location_matching is None else use_location_matching
    )

    profile = build_profile(
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching_value,
    )

    session = request.state.session

    session.profile = build_profile(
        name=session.profile.get("name") if session.profile else None,
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching_value,
        confirmed=True,
    )

    program_groups = all_program_groups()
    total_programs = sum_programs(program_groups)

    cached = session.ranking_cache.get(
        profile,
        MatchTarget.PROGRAMS,
    )

    ranking_cached = cached is not None
    cached_ranked = cached.ranked if cached else []

    params = profile_query_params(profile)

    rank_stream_url = "/api/rank-programs"
    if params:
        rank_stream_url += "?" + urlencode(params)

    return templates.TemplateResponse(
        request,
        "programs.html",
        {
            "profile": profile,
            "match_target": MatchTarget.PROGRAMS.value,
            "chat_profile_url": profile_chat_url(profile),
            "rank_stream_url": rank_stream_url,
            "ranking_cached": ranking_cached,
            "cached_ranked": cached_ranked,
            "completed_items": cached.completed_items if cached else 0,
            "total_items": (cached.total_items if cached else len(program_groups)),
            "completed_units": cached.completed_units if cached else 0,
            "total_units": (cached.total_units if cached else total_programs),
            "is_done": ranking_cached,
            "cached_elapsed_seconds": (cached.elapsed_seconds if cached else 0),
            "item_singular": "career",
            "item_plural": "careers",
            "unit_singular": "registered program",
            "unit_plural": "registered programs",
            "region_filter_options": REGION_FILTER_OPTIONS,
            "show_license_filter": False,
            "filter_item_singular": "career",
            "filter_item_plural": "careers",
        },
    )


# ── Single program group page ─────────────────────────────────────────────────


@app.get("/programs/{soc_code}")
async def program_detail_page(
    request: Request,
    soc_code: str,
):
    """Serve a registered apprenticeship program-group detail page."""
    program_group = get_program_group(soc_code)

    if program_group is None:
        raise HTTPException(status_code=404)

    return templates.TemplateResponse(
        request,
        "program.html",
        {
            "program_group": program_group,
            "program_title": program_group_title(program_group),
        },
    )


# ── Program ranking ───────────────────────────────────────────────────────────


@app.get("/api/rank-programs")
async def rank_programs_stream(
    request: Request,
    likes: list[str] = Query(default=[]),
    dislikes: list[str] = Query(default=[]),
    location: str | None = None,
    transportation: str | None = None,
    use_location_matching: bool = True,
):
    """Rank registered apprenticeship career groups and stream results."""
    session = request.state.session

    profile = build_profile(
        likes=likes,
        dislikes=dislikes,
        location=location,
        transportation=transportation,
        use_location_matching=use_location_matching,
    )

    cached = session.ranking_cache.get(
        profile,
        MatchTarget.PROGRAMS,
    )

    if cached:
        log_event(
            request,
            "ranking_cache_hit",
            target=MatchTarget.PROGRAMS.value,
            model=SCORING_MODEL_NAME,
            items=len(cached.ranked),
            cached=True,
            original_elapsed_seconds=cached.elapsed_seconds,
        )

        return EventSourceResponse(
            stream_cached_ranking(
                cached,
                render=render,
                adapter=PROGRAM_RANKING_ADAPTER,
            )
        )

    request_started_at = time.perf_counter()

    program_groups = all_program_groups()
    total_programs = sum_programs(program_groups)

    group_index = {
        group["socCode"]: index for index, group in enumerate(program_groups)
    }

    batches = chunk_items(
        program_groups,
        RANKING_STREAM_CONFIG.batch_size,
    )

    log_event(
        request,
        "ranking_started",
        target=MatchTarget.PROGRAMS.value,
        model=SCORING_MODEL_NAME,
        items=len(program_groups),
        units=total_programs,
        batches=len(batches),
        batch_size=RANKING_STREAM_CONFIG.batch_size,
        concurrency=RANKING_STREAM_CONFIG.max_concurrency,
        cached=False,
    )

    return EventSourceResponse(
        stream_ranking(
            request=request,
            session=session,
            target=MatchTarget.PROGRAMS,
            profile=profile,
            request_started_at=request_started_at,
            items=program_groups,
            total_units=total_programs,
            item_index=group_index,
            batches=batches,
            score_items=_score_program_groups,
            adapter=PROGRAM_RANKING_ADAPTER,
            render=render,
            config=RANKING_STREAM_CONFIG,
        )
    )
