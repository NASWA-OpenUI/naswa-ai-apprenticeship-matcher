import asyncio
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from db import all_opportunities, get_opportunity, load as load_db
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from strands import Agent
from strands.models import BedrockModel


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

templates = Jinja2Templates(directory=BASE_DIR / "templates")

# ── Logging setup and filters ───────────────────────────────────────────────────

ROOT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
NASWA_LOG_LEVEL = os.getenv("NASWA_LOG_LEVEL", ROOT_LOG_LEVEL).upper()

logging.basicConfig(
    level=getattr(logging, ROOT_LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger("naswa")
logger.setLevel(getattr(logging, NASWA_LOG_LEVEL, logging.INFO))

def _describe_exception(exc: Exception) -> str:
    """Return a compact message for logs and local/demo UI errors."""
    response = getattr(exc, "response", None)

    if isinstance(response, dict):
        error = response.get("Error", {})
        code = error.get("Code", exc.__class__.__name__)
        message = error.get("Message", str(exc))
        return f"{code}: {message}"

    return f"{exc.__class__.__name__}: {exc}"


# ── Jinja2 filters ────────────────────────────────────────────────────────────

_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _format_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        y, m, d = iso.split("-")
        return f"{_MONTHS[int(m) - 1]} {int(d)}, {y}"
    except ValueError, IndexError:
        return iso


def _format_wage(n: float | None) -> str:
    if n is None:
        return "—"
    return "$" + f"{round(n):,}"


templates.env.filters["format_date"] = _format_date
templates.env.filters["format_wage"] = _format_wage


def render(name: str, **ctx) -> str:
    """Render a template fragment to string (no Request needed)."""
    return templates.env.get_template(name).render(**ctx)


# ── Profile helpers ───────────────────────────────────────────────────────────


def _strip_profile(text: str) -> str:
    """Remove <thinking> and <profile> XML from text so tokens display cleanly."""
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text)
    text = re.sub(r"<thinking>[\s\S]*$", "", text)  # partial tag mid-stream
    text = re.sub(r"<profile>[\s\S]*?</profile>", "", text)
    text = re.sub(r"<profile>[\s\S]*$", "", text)  # partial tag mid-stream
    return text.strip()


def _extract_profile(text: str) -> dict | None:
    """Return parsed profile JSON from a completed agent response, or None."""
    m = re.search(r"<profile>([\s\S]*?)</profile>", text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# ── Agent setup ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are conducting a short guided conversation to learn about a user
so the app can suggest registered apprenticeships that may fit them.
The user has already been greeted and asked for their name.

Follow these steps exactly — do not skip steps or add extra conversation.

STEP 1
If the user's message is only their name, respond only with:
"Hi [name]! Tell me a little about yourself — what you’re into, what you’re good at, or what kind of work sounds interesting to you."

Stop there. Do not continue to STEP 2 until the user sends a separate message describing themselves.

STEP 2
When the user describes their interests, hobbies, strengths, or work preferences,
identify 2-3 short underlying themes
(e.g. "working with your hands", "helping people", "solving problems", "being outdoors", "creative work").

Write your analysis conversationally:
"So it sounds like you enjoy [theme 1] and [theme 2] — is that right?"

Then, on a new line by itself, output exactly (with real values filled in):
<profile>{"name":"[name]","hobbies":"[their exact words]","interests":["theme 1","theme 2"],"confirmed":false}</profile>

Only run this step if the user's latest actual message describes their interests, hobbies, strengths, or work preferences.
Do not invent details.

STEP 3
If the user confirms (yes / correct / right / sounds good / etc.), respond briefly:
"Great, that's all I need!"

Then on a new line by itself output:
<profile>{"name":"[name]","hobbies":"[their exact words]","interests":["theme 1","theme 2"],"confirmed":true}</profile>

STEP 4
If the user does NOT confirm, ask what you got wrong, then return to STEP 2.

Rules:
- Keep all responses brief and friendly.
- Only respond to the user's latest actual message.
- Do not invent, assume, simulate, or write future user responses.
- Never write text like "User's response:".
- Never continue to the next step until the user has actually sent the required message.
- Output exactly one assistant turn per user message.
- Never mention, explain, or draw attention to the <profile> tag — it is invisible to the user.
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

# ── Set up lightweight sessions ────────────────────────────────────────────────

SESSION_COOKIE_NAME = "tyler_demo_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7 days


@dataclass
class ChatSession:
    """Ephemeral browser session for the internal demo."""

    agent: Agent = field(default_factory=make_agent)
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    profile: dict | None = None
    last_seen: float = field(default_factory=time.time)
    active_stream_id: str | None = None


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


# ── ONET scoring ──────────────────────────────────────────────────────────────

RANKING_BATCH_SIZE = int(os.getenv("RANKING_BATCH_SIZE", "10"))
RANKING_MAX_CONCURRENCY = int(os.getenv("RANKING_MAX_CONCURRENCY", "3"))

TIER_ORDER = {"Strong": 0, "Moderate": 1, "Weak": 2}


def _chunks(items: list[dict], size: int) -> list[list[dict]]:
    """Split a list into fixed-size chunks."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _normalize_tier(tier: str | None) -> str:
    """Keep unexpected model output from breaking CSS/classes/sorting."""
    if tier in TIER_ORDER:
        return tier
    return "Weak"


def _build_ranked_items(
    batch_jobs: list[dict],
    scores: list[dict],
    job_index: dict[str, int],
) -> list[dict]:
    """Attach model scores back to jobs and sort this batch by tier."""
    score_map = {
        score.get("id"): score
        for score in scores
        if isinstance(score, dict) and score.get("id")
    }

    ranked = []

    for job in batch_jobs:
        score = score_map.get(job["id"], {})
        tier = _normalize_tier(score.get("tier"))

        ranked.append(
            {
                "id": job["id"],
                "tier": tier,
                "tier_order": TIER_ORDER.get(tier, 3),
                "sort_index": job_index[job["id"]],
                "explanation": score.get("explanation", ""),
                "posting": job["posting"],
            }
        )


    return sorted(
        ranked,
        key=lambda item: (item["tier_order"], item["sort_index"]),
    )

async def _score_jobs(interests: list[str], onet_jobs: list[dict]) -> list[dict]:
    """One LLM call that tier-ranks all ONET jobs against user interests."""
    summaries = []
    for job in onet_jobs:
        o = job["onet"]
        try:
            skills = [s["name"] for s in (o["skills"]["data"]["element"] or [])[:5]]
        except KeyError, TypeError:
            skills = []
        try:
            activities = [
                a["title"]
                for a in (o["detailed_work_activities"]["data"]["activity"] or [])[:5]
            ]
        except KeyError, TypeError:
            activities = []
        try:
            styles = [
                s["name"] for s in (o["work_styles"]["data"]["element"] or [])[:4]
            ]
        except KeyError, TypeError:
            styles = []
        summaries.append(
            {
                "id": job["id"],
                "title": job["posting"]["jobTitle"],
                "description": (o.get("description") or "")[:200],
                "skills": skills,
                "activities": activities,
                "work_styles": styles,
            }
        )

    prompt = (
        f"The user enjoys: {', '.join(interests)}.\n\n"
        "Score each job as Strong, Moderate, or Weak match for someone with those interests.\n"
        "Return ONLY a JSON array — no markdown, no extra text:\n"
        '[{"id":"<id>","tier":"Strong|Moderate|Weak","explanation":"1-2 sentences why"}]\n\n'
        f"Jobs:\n{json.dumps(summaries, indent=2)}"
    )

    scorer = Agent(
        model=make_bedrock_model(SCORING_MODEL_NAME, streaming=False),
        callback_handler=None,
    )

    result = await scorer.invoke_async(prompt)
    raw = str(result)

    raw = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        raw = m.group()
    return json.loads(raw)


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

# ── Chat ──────────────────────────────────────────────────────────────────────


@app.get("/chat")
async def chat_page(request: Request):
    """Serve the guided chat page."""
    session_id, session, needs_cookie = _get_or_create_session(request)

    response = templates.TemplateResponse(
        request,
        "chat.html",
        {"profile": session.profile},
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
                    display = _strip_profile(full_text)
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
                yield {"event": "message", "data": msg_html}
                continue

            logger.debug("Chat agent completed")

            profile = _extract_profile(full_text)
            final_text = _strip_profile(full_text)

            msg_html = render("_message.html", role="assistant", content=final_text)
            logger.debug("Sending assistant message event")

            yield {"event": "clear-stream", "data": ""}
            yield {"event": "message", "data": msg_html}

            if profile:
                session.profile = profile

                if profile.get("confirmed"):
                    interests = profile.get("interests", [])
                    ranked_url = "/opportunities?" + urlencode(
                        [("ranked", "true")] + [("interests", i) for i in interests]
                    )
                    card_html = render(
                        "_profile_card.html", profile=profile, ranked_url=ranked_url
                    )
                    yield {"event": "profile-confirmed", "data": card_html}

    response = EventSourceResponse(generate())

    if needs_cookie:
        _set_session_cookie(response, session_id)

    return response


# ── Opportunities pages ───────────────────────────────────────────────────────


@app.get("/opportunities")
async def opportunities_page(
    request: Request,
    ranked: bool = False,
    interests: list[str] = Query(default=[]),
):
    """Serve the opportunities list, optionally in ranked mode."""
    if ranked and interests:
        all_jobs = all_opportunities()
        onet_jobs = [j for j in all_jobs if j.get("onet") is not None]
        no_onet_jobs = [j for j in all_jobs if j.get("onet") is None]

        rank_stream_url = "/api/rank-opportunities?" + urlencode(
            [("interests", i) for i in interests]
        )

        unranked = [{"id": j["id"], "posting": j["posting"]} for j in no_onet_jobs]

        return templates.TemplateResponse(
            request,
            "opportunities.html",
            {
                "ranked": True,
                "rank_stream_url": rank_stream_url,
                "interests": interests,
                "ranked_total": len(onet_jobs),
                "unranked": unranked,
                "completed_jobs": 0,
                "total_jobs": len(onet_jobs),
                "completed_batches": 0,
                "total_batches": len(_chunks(onet_jobs, RANKING_BATCH_SIZE)),
                "is_done": False,
            },
        )
    return templates.TemplateResponse(
        request,
        "opportunities.html",
        {"ranked": False, "opportunities": all_opportunities()},
    )


@app.get("/opportunities/{slug}")
async def opportunity_detail_page(request: Request, slug: str):
    """Serve the opportunity detail page."""
    opp = get_opportunity(slug)
    if opp is None:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "opportunity.html", {"opp": opp})


# ── Ranking ───────────────────────────────────────────────────────────────────


@app.get("/api/rank-opportunities")
async def rank_opportunities_stream(
    request: Request,
    interests: list[str] = Query(...),
):
    """
    Rank ONET jobs in parallel batches and stream result cards as each batch completes.
    """
    benchmark_id = secrets.token_hex(4)
    request_started_at = time.perf_counter()

    all_jobs = all_opportunities()
    onet_jobs = [j for j in all_jobs if j.get("onet") is not None]

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
                    scores = await _score_jobs(interests, batch_jobs)

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

                    ranked = _build_ranked_items(
                        batch_jobs=batch_jobs,
                        scores=scores,
                        job_index=job_index,
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

                if result["error"]:
                    yield {
                        "event": "batch-error",
                        "data": (
                            f"<p class='empty-state surface surface--shadow'>"
                            f"One ranking batch failed: {result['error']}"
                            f"</p>"
                        ),
                    }
                else:
                    cards_html = render(
                        "_rank_cards.html",
                        ranked=result["ranked"],
                    )

                    yield {
                        "event": "batch",
                        "data": cards_html,
                    }

                progress_html = render(
                    "_rank_progress.html",
                    completed_jobs=completed_jobs,
                    total_jobs=len(onet_jobs),
                    completed_batches=completed_batches,
                    total_batches=total_batches,
                    is_done=False,
                )

                yield {
                    "event": "progress",
                    "data": progress_html,
                }

            total_elapsed_ms = (time.perf_counter() - request_started_at) * 1000

            logger.info(
                "Streaming opportunity ranking completed id=%s jobs=%s batches=%s total_elapsed_ms=%.1f",
                benchmark_id,
                len(onet_jobs),
                total_batches,
                total_elapsed_ms,
            )

            final_progress_html = render(
                "_rank_progress.html",
                completed_jobs=completed_jobs,
                total_jobs=len(onet_jobs),
                completed_batches=completed_batches,
                total_batches=total_batches,
                is_done=True,
            )

            yield {
                "event": "progress",
                "data": final_progress_html,
            }

            yield {
                "event": "done",
                "data": "Ranking complete.",
            }

        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()

    return EventSourceResponse(generate())
