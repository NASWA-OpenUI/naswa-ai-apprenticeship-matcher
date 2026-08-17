import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import Request

from naswa_matcher.agents import SCORING_MODEL_NAME
from naswa_matcher.app_logging import (
    describe_exception,
    log_event,
    log_exception,
)
from naswa_matcher.match_target import MatchTarget
from naswa_matcher.opportunity_stats import sum_openings
from naswa_matcher.ranking import build_ranked_items, sort_ranked_items
from naswa_matcher.ranking_cache import RankingCacheEntry
from naswa_matcher.sessions import ChatSession

logger = logging.getLogger("naswa.ranking_stream")

ScoreJobs = Callable[[dict, list[dict]], Awaitable[list[dict]]]
Render = Callable[..., str]


@dataclass(frozen=True)
class RankingStreamConfig:
    """Operational settings for streamed opportunity ranking."""

    batch_size: int = 10
    max_concurrency: int = 3
    max_attempts: int = 3
    retry_delay_seconds: float = 1.0


@dataclass
class RankingBatchResult:
    """Result of ranking one batch of opportunities."""

    batch_number: int
    jobs: list[dict]
    ranked: list[dict]
    elapsed_ms: float
    error: str | None = None


@dataclass
class RankingProgress:
    """Accumulated progress for one opportunity ranking run."""

    completed_batches: int = 0
    completed_jobs: int = 0
    completed_openings: int = 0
    ranked: list[dict] = field(default_factory=list)
    had_batch_error: bool = False

    def record(self, result: RankingBatchResult) -> None:
        """Record the outcome of one completed ranking batch."""
        self.completed_batches += 1
        self.completed_jobs += len(result.jobs)
        self.completed_openings += sum_openings(result.jobs)

        if result.error:
            self.had_batch_error = True
        else:
            self.ranked.extend(result.ranked)


def chunk_opportunities(
    items: list[dict],
    size: int,
) -> list[list[dict]]:
    """Split opportunities into fixed-size ranking batches."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _render_rank_count(
    *,
    completed_jobs: int,
    total_jobs: int,
    completed_openings: int,
) -> str:
    """Render the compact opportunity/opening count used by ranking SSE events."""
    opportunity_label = "opportunity" if total_jobs == 1 else "opportunities"
    opening_label = "opening" if completed_openings == 1 else "openings"

    return (
        f'<span id="ranked-count" class="ranked-count">{completed_jobs}</span> '
        f"of {total_jobs} {opportunity_label} analyzed "
        f'<span aria-hidden="true"> · </span>'
        f'<span id="openings-count">{completed_openings}</span> {opening_label}'
    )


async def stream_cached_ranking(
    cached: RankingCacheEntry,
    *,
    render: Render,
):
    """Yield SSE events for a completed ranking loaded from session cache."""
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


async def _score_jobs_with_retry(
    *,
    profile: dict,
    batch_jobs: list[dict],
    request_id: str,
    batch_number: int,
    total_batches: int,
    score_jobs: ScoreJobs,
    config: RankingStreamConfig,
) -> list[dict]:
    """Score one batch, retrying failed scoring attempts."""
    scores = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            scores = await score_jobs(profile, batch_jobs)
            break

        except Exception as exc:
            error_message = describe_exception(exc)

            if attempt == config.max_attempts:
                raise

            delay_seconds = config.retry_delay_seconds * attempt

            logger.warning(
                "Ranking batch attempt failed; retrying "
                "request_id=%s batch=%s/%s jobs=%s attempt=%s/%s "
                "retry_in=%.2fs error=%s",
                request_id,
                batch_number,
                total_batches,
                len(batch_jobs),
                attempt,
                config.max_attempts,
                delay_seconds,
                error_message,
            )

            await asyncio.sleep(delay_seconds)

    if scores is None:
        raise RuntimeError("Ranking batch did not return scores.")

    return scores


async def _rank_batch(
    *,
    request: Request,
    profile: dict,
    batch_number: int,
    batch_jobs: list[dict],
    total_batches: int,
    job_index: dict[str, int],
    semaphore: asyncio.Semaphore,
    score_jobs: ScoreJobs,
    config: RankingStreamConfig,
) -> RankingBatchResult:
    """Rank one batch of opportunities, returning success or error details."""
    request_id = request.state.request_id

    async with semaphore:
        batch_started_at = time.perf_counter()

        logger.debug(
            "Ranking batch started request_id=%s batch=%s/%s jobs=%s model=%s",
            request_id,
            batch_number,
            total_batches,
            len(batch_jobs),
            SCORING_MODEL_NAME,
        )

        try:
            scores = await _score_jobs_with_retry(
                profile=profile,
                batch_jobs=batch_jobs,
                request_id=request_id,
                batch_number=batch_number,
                total_batches=total_batches,
                score_jobs=score_jobs,
                config=config,
            )

            if len(scores) != len(batch_jobs):
                logger.warning(
                    "Ranking batch returned unexpected score count "
                    "request_id=%s batch=%s/%s jobs=%s scores=%s model=%s",
                    request_id,
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
                "Ranking batch completed "
                "request_id=%s batch=%s/%s jobs=%s scores=%s elapsed_ms=%.1f",
                request_id,
                batch_number,
                total_batches,
                len(batch_jobs),
                len(scores),
                elapsed_ms,
            )

            return RankingBatchResult(
                batch_number=batch_number,
                jobs=batch_jobs,
                ranked=ranked,
                elapsed_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - batch_started_at) * 1000
            error_message = describe_exception(exc)

            log_exception(
                request,
                "ranking_batch_failed",
                error=error_message,
                model=SCORING_MODEL_NAME,
                batch=batch_number,
                total_batches=total_batches,
                jobs=len(batch_jobs),
                elapsed_ms=round(elapsed_ms, 1),
            )

            return RankingBatchResult(
                batch_number=batch_number,
                jobs=batch_jobs,
                ranked=[],
                elapsed_ms=elapsed_ms,
                error=error_message,
            )


async def stream_ranking(
    *,
    request: Request,
    session: ChatSession,
    target: MatchTarget,
    profile: dict,
    request_started_at: float,
    onet_jobs: list[dict],
    total_openings: int,
    job_index: dict[str, int],
    batches: list[list[dict]],
    score_jobs: ScoreJobs,
    render: Render,
    config: RankingStreamConfig,
):
    """Rank opportunity batches concurrently and yield SSE ranking events."""
    total_batches = len(batches)
    semaphore = asyncio.Semaphore(config.max_concurrency)

    progress = RankingProgress()
    disconnected = False

    tasks = [
        asyncio.create_task(
            _rank_batch(
                request=request,
                profile=profile,
                batch_number=batch_number,
                batch_jobs=batch_jobs,
                total_batches=total_batches,
                job_index=job_index,
                semaphore=semaphore,
                score_jobs=score_jobs,
                config=config,
            )
        )
        for batch_number, batch_jobs in enumerate(batches, start=1)
    ]

    try:
        for task in asyncio.as_completed(tasks):
            if await request.is_disconnected():
                disconnected = True

                logger.info(
                    "Streaming opportunity ranking disconnected "
                    "request_id=%s completed_batches=%s/%s",
                    request.state.request_id,
                    progress.completed_batches,
                    total_batches,
                )
                break

            result = await task
            progress.record(result)

            if result.error:
                yield {
                    "event": "batch-error",
                    "data": (
                        "<p class='empty-state surface surface--shadow'>"
                        f"One ranking batch failed: {result.error}"
                        "</p>"
                    ),
                }

            else:
                cards_html = render(
                    "_rank_cards.html",
                    ranked=result.ranked,
                )

                yield {
                    "event": "batch",
                    "data": cards_html,
                }

            elapsed_seconds = round(time.perf_counter() - request_started_at)

            progress_html = render(
                "_rank_progress.html",
                completed_jobs=progress.completed_jobs,
                total_jobs=len(onet_jobs),
                completed_openings=progress.completed_openings,
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
                    completed_jobs=progress.completed_jobs,
                    total_jobs=len(onet_jobs),
                    completed_openings=progress.completed_openings,
                ),
            }

        if disconnected:
            return

        total_elapsed_ms = (time.perf_counter() - request_started_at) * 1000
        total_elapsed_seconds = round(total_elapsed_ms / 1000)

        final_ranked = sort_ranked_items(progress.ranked, profile)

        if progress.completed_jobs == len(onet_jobs) and not progress.had_batch_error:
            session.ranking_cache.put(
                profile,
                target,
                RankingCacheEntry(
                    profile=profile,
                    ranked=final_ranked,
                    completed_jobs=progress.completed_jobs,
                    total_jobs=len(onet_jobs),
                    completed_openings=progress.completed_openings,
                    total_openings=total_openings,
                    elapsed_seconds=total_elapsed_seconds,
                    is_complete=True,
                ),
            )

        log_event(
            request,
            "ranking_completed",
            model=SCORING_MODEL_NAME,
            jobs=len(onet_jobs),
            completed_jobs=progress.completed_jobs,
            batches=total_batches,
            batch_size=config.batch_size,
            concurrency=config.max_concurrency,
            elapsed_ms=round(total_elapsed_ms, 1),
            had_batch_error=progress.had_batch_error,
            cached=False,
        )

        final_progress_html = render(
            "_rank_progress.html",
            completed_jobs=progress.completed_jobs,
            total_jobs=len(onet_jobs),
            completed_openings=progress.completed_openings,
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
                completed_jobs=progress.completed_jobs,
                total_jobs=len(onet_jobs),
                completed_openings=progress.completed_openings,
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
