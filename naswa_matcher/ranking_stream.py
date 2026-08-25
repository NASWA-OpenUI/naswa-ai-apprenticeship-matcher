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
from naswa_matcher.ranking import sort_ranked_items
from naswa_matcher.ranking_cache import RankingCacheEntry
from naswa_matcher.sessions import ChatSession

logger = logging.getLogger("naswa.ranking_stream")

ScoreItems = Callable[[dict, list[dict]], Awaitable[list[dict]]]
BuildRankedItems = Callable[
    [list[dict], list[dict], dict[str, int]],
    list[dict],
]
CountUnits = Callable[[list[dict]], int]
Render = Callable[..., str]


@dataclass(frozen=True)
class RankingStreamConfig:
    """Operational settings for streamed ranking."""

    batch_size: int = 10
    max_concurrency: int = 3
    max_attempts: int = 3
    retry_delay_seconds: float = 1.0


@dataclass(frozen=True)
class RankingStreamAdapter:
    """Domain-specific behavior and labels used by shared ranking orchestration."""

    cards_template: str
    item_singular: str
    item_plural: str
    unit_singular: str
    unit_plural: str
    build_ranked_items: BuildRankedItems
    count_units: CountUnits


@dataclass
class RankingBatchResult:
    """Result of ranking one batch of items."""

    batch_number: int
    items: list[dict]
    ranked: list[dict]
    elapsed_ms: float
    error: str | None = None


@dataclass
class RankingProgress:
    """Accumulated progress for one ranking run."""

    completed_batches: int = 0
    completed_items: int = 0
    completed_units: int = 0
    ranked: list[dict] = field(default_factory=list)
    had_batch_error: bool = False

    def record(
        self,
        result: RankingBatchResult,
        *,
        count_units: CountUnits,
    ) -> None:
        """Record the outcome of one completed ranking batch."""
        self.completed_batches += 1
        self.completed_items += len(result.items)
        self.completed_units += count_units(result.items)

        if result.error:
            self.had_batch_error = True
        else:
            self.ranked.extend(result.ranked)


def chunk_items(
    items: list[dict],
    size: int,
) -> list[list[dict]]:
    """Split ranking items into fixed-size batches."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _render_rank_count(
    *,
    completed_items: int,
    total_items: int,
    completed_units: int,
    adapter: RankingStreamAdapter,
) -> str:
    """Render the compact item/unit count used by ranking SSE events."""
    item_label = adapter.item_singular if total_items == 1 else adapter.item_plural

    unit_label = adapter.unit_singular if completed_units == 1 else adapter.unit_plural

    return (
        f'<span id="ranked-count" class="ranked-count">'
        f"{completed_items}</span> "
        f"of {total_items} {item_label} analyzed "
        f'<span aria-hidden="true"> · </span>'
        f'<span id="units-count">{completed_units}</span> '
        f"{unit_label}"
    )


async def stream_cached_ranking(
    cached: RankingCacheEntry,
    *,
    render: Render,
    adapter: RankingStreamAdapter,
):
    """Yield SSE events for a completed ranking loaded from session cache."""
    cards_html = render(
        adapter.cards_template,
        ranked=cached.ranked,
    )

    if cards_html.strip():
        yield {
            "event": "batch",
            "data": cards_html,
        }

    progress_html = render(
        "_rank_progress.html",
        completed_items=cached.completed_items,
        total_items=cached.total_items,
        completed_units=cached.completed_units,
        total_units=cached.total_units,
        is_done=True,
        item_singular=adapter.item_singular,
        item_plural=adapter.item_plural,
        unit_singular=adapter.unit_singular,
        unit_plural=adapter.unit_plural,
    )

    yield {
        "event": "progress",
        "data": progress_html,
    }

    yield {
        "event": "rank-count",
        "data": _render_rank_count(
            completed_items=cached.completed_items,
            total_items=cached.total_items,
            completed_units=cached.completed_units,
            adapter=adapter,
        ),
    }

    yield {
        "event": "done",
        "data": str(cached.elapsed_seconds),
    }


async def _score_items_with_retry(
    *,
    profile: dict,
    batch_items: list[dict],
    request_id: str,
    target: MatchTarget,
    batch_number: int,
    total_batches: int,
    score_items: ScoreItems,
    config: RankingStreamConfig,
) -> list[dict]:
    """Score one batch, retrying failed scoring attempts."""
    for attempt in range(1, config.max_attempts + 1):
        try:
            return await score_items(
                profile,
                batch_items,
            )

        except Exception as exc:
            error_message = describe_exception(exc)

            if attempt == config.max_attempts:
                raise

            delay_seconds = config.retry_delay_seconds * attempt

            logger.warning(
                "Ranking batch attempt failed; retrying "
                "request_id=%s target=%s batch=%s/%s items=%s "
                "attempt=%s/%s retry_in=%.2fs error=%s",
                request_id,
                target.value,
                batch_number,
                total_batches,
                len(batch_items),
                attempt,
                config.max_attempts,
                delay_seconds,
                error_message,
            )

            await asyncio.sleep(delay_seconds)

    raise RuntimeError("Ranking batch did not return scores.")


async def _rank_batch(
    *,
    request: Request,
    target: MatchTarget,
    profile: dict,
    batch_number: int,
    batch_items: list[dict],
    total_batches: int,
    item_index: dict[str, int],
    semaphore: asyncio.Semaphore,
    score_items: ScoreItems,
    adapter: RankingStreamAdapter,
    config: RankingStreamConfig,
) -> RankingBatchResult:
    """Rank one batch of items, returning success or error details."""
    request_id = request.state.request_id

    async with semaphore:
        batch_started_at = time.perf_counter()

        logger.debug(
            "Ranking batch started "
            "request_id=%s target=%s batch=%s/%s items=%s model=%s",
            request_id,
            target.value,
            batch_number,
            total_batches,
            len(batch_items),
            SCORING_MODEL_NAME,
        )

        try:
            scores = await _score_items_with_retry(
                profile=profile,
                batch_items=batch_items,
                request_id=request_id,
                target=target,
                batch_number=batch_number,
                total_batches=total_batches,
                score_items=score_items,
                config=config,
            )

            if len(scores) != len(batch_items):
                logger.warning(
                    "Ranking batch returned unexpected score count "
                    "request_id=%s target=%s batch=%s/%s "
                    "items=%s scores=%s model=%s",
                    request_id,
                    target.value,
                    batch_number,
                    total_batches,
                    len(batch_items),
                    len(scores),
                    SCORING_MODEL_NAME,
                )

            ranked = adapter.build_ranked_items(
                batch_items,
                scores,
                item_index,
            )

            elapsed_ms = (time.perf_counter() - batch_started_at) * 1000

            logger.debug(
                "Ranking batch completed "
                "request_id=%s target=%s batch=%s/%s "
                "items=%s scores=%s elapsed_ms=%.1f",
                request_id,
                target.value,
                batch_number,
                total_batches,
                len(batch_items),
                len(scores),
                elapsed_ms,
            )

            return RankingBatchResult(
                batch_number=batch_number,
                items=batch_items,
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
                target=target.value,
                model=SCORING_MODEL_NAME,
                batch=batch_number,
                total_batches=total_batches,
                items=len(batch_items),
                elapsed_ms=round(elapsed_ms, 1),
            )

            return RankingBatchResult(
                batch_number=batch_number,
                items=batch_items,
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
    items: list[dict],
    total_units: int,
    item_index: dict[str, int],
    batches: list[list[dict]],
    score_items: ScoreItems,
    adapter: RankingStreamAdapter,
    render: Render,
    config: RankingStreamConfig,
):
    """Rank batches concurrently and yield shared SSE ranking events."""
    total_batches = len(batches)
    semaphore = asyncio.Semaphore(config.max_concurrency)

    progress = RankingProgress()
    disconnected = False

    tasks = [
        asyncio.create_task(
            _rank_batch(
                request=request,
                target=target,
                profile=profile,
                batch_number=batch_number,
                batch_items=batch_items,
                total_batches=total_batches,
                item_index=item_index,
                semaphore=semaphore,
                score_items=score_items,
                adapter=adapter,
                config=config,
            )
        )
        for batch_number, batch_items in enumerate(
            batches,
            start=1,
        )
    ]

    try:
        for task in asyncio.as_completed(tasks):
            if await request.is_disconnected():
                disconnected = True

                logger.info(
                    "Streaming ranking disconnected "
                    "request_id=%s target=%s "
                    "completed_batches=%s/%s",
                    request.state.request_id,
                    target.value,
                    progress.completed_batches,
                    total_batches,
                )

                break

            result = await task

            progress.record(
                result,
                count_units=adapter.count_units,
            )

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
                    adapter.cards_template,
                    ranked=result.ranked,
                )

                yield {
                    "event": "batch",
                    "data": cards_html,
                }

            elapsed_seconds = round(time.perf_counter() - request_started_at)

            progress_html = render(
                "_rank_progress.html",
                completed_items=progress.completed_items,
                total_items=len(items),
                completed_units=progress.completed_units,
                total_units=total_units,
                is_done=False,
                elapsed_seconds=elapsed_seconds,
                item_singular=adapter.item_singular,
                item_plural=adapter.item_plural,
                unit_singular=adapter.unit_singular,
                unit_plural=adapter.unit_plural,
            )

            yield {
                "event": "progress",
                "data": progress_html,
            }

            yield {
                "event": "rank-count",
                "data": _render_rank_count(
                    completed_items=progress.completed_items,
                    total_items=len(items),
                    completed_units=progress.completed_units,
                    adapter=adapter,
                ),
            }

        if disconnected:
            return

        total_elapsed_ms = (time.perf_counter() - request_started_at) * 1000

        total_elapsed_seconds = round(total_elapsed_ms / 1000)

        final_ranked = sort_ranked_items(progress.ranked)

        if progress.completed_items == len(items) and not progress.had_batch_error:
            session.ranking_cache.put(
                profile,
                target,
                RankingCacheEntry(
                    ranked=final_ranked,
                    completed_items=progress.completed_items,
                    total_items=len(items),
                    completed_units=progress.completed_units,
                    total_units=total_units,
                    elapsed_seconds=total_elapsed_seconds,
                    is_complete=True,
                ),
            )

        log_event(
            request,
            "ranking_completed",
            target=target.value,
            model=SCORING_MODEL_NAME,
            items=len(items),
            completed_items=progress.completed_items,
            units=total_units,
            completed_units=progress.completed_units,
            batches=total_batches,
            batch_size=config.batch_size,
            concurrency=config.max_concurrency,
            elapsed_ms=round(total_elapsed_ms, 1),
            had_batch_error=progress.had_batch_error,
            cached=False,
        )

        final_progress_html = render(
            "_rank_progress.html",
            completed_items=progress.completed_items,
            total_items=len(items),
            completed_units=progress.completed_units,
            total_units=total_units,
            is_done=True,
            item_singular=adapter.item_singular,
            item_plural=adapter.item_plural,
            unit_singular=adapter.unit_singular,
            unit_plural=adapter.unit_plural,
        )

        yield {
            "event": "progress",
            "data": final_progress_html,
        }

        yield {
            "event": "rank-count",
            "data": _render_rank_count(
                completed_items=progress.completed_items,
                total_items=len(items),
                completed_units=progress.completed_units,
                adapter=adapter,
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
