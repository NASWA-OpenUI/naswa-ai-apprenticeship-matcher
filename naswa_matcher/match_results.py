from naswa_matcher.location_data import LABOR_MARKET_REGIONS
from naswa_matcher.match_target import MatchTarget
from naswa_matcher.opportunity_stats import sum_openings
from naswa_matcher.profile import (
    build_profile_for_target,
    profile_chat_url,
    profile_url,
)
from naswa_matcher.program_ranking import sum_programs
from naswa_matcher.ranking_cache import RankingCacheEntry
from naswa_matcher.sessions import ChatSession


def _ranking_cache_context(
    cached: RankingCacheEntry | None,
    *,
    total_items: int,
    total_units: int,
) -> dict:
    """Return template context describing current ranking progress."""
    return {
        "ranking_cached": cached is not None,
        "cached_ranked": cached.ranked if cached else [],
        "completed_items": cached.completed_items if cached else 0,
        "total_items": cached.total_items if cached else total_items,
        "completed_units": cached.completed_units if cached else 0,
        "total_units": cached.total_units if cached else total_units,
        "is_done": cached is not None,
        "cached_elapsed_seconds": cached.elapsed_seconds if cached else 0,
    }


def _prepare_results_session(
    session: ChatSession,
    target: MatchTarget,
    *,
    name: str | None,
    likes: list[str],
    dislikes: list[str],
    transportation: str | None = None,
) -> dict:
    """Set the active match target and confirmed display profile."""
    session.set_match_target(target)

    existing_name = session.profile.get("name") if session.profile else None

    display_profile = build_profile_for_target(
        target,
        name=existing_name if name is None else name,
        likes=likes,
        dislikes=dislikes,
        transportation=transportation,
        confirmed=True,
    )

    session.profile = display_profile

    return display_profile


def build_opportunity_results_context(
    *,
    session: ChatSession,
    opportunities: list[dict],
    likes: list[str],
    dislikes: list[str],
    transportation: str | None,
    name: str | None,
    demo: bool,
    saved_opportunity_ids: tuple[str, ...],
) -> dict:
    """Build template context for personalized opportunity results."""
    target = MatchTarget.OPPORTUNITIES

    ranking_profile = build_profile_for_target(
        target,
        likes=likes,
        dislikes=dislikes,
        transportation=transportation,
    )

    display_profile = _prepare_results_session(
        session,
        target,
        name=name,
        likes=likes,
        dislikes=dislikes,
        transportation=transportation,
    )

    total_openings = sum_openings(opportunities)

    cached = session.ranking_cache.get(
        ranking_profile,
        target,
    )

    return {
        "rank_stream_url": profile_url(
            "/api/rank-opportunities",
            ranking_profile,
        ),
        "profile": display_profile,
        "match_target": target.value,
        "chat_profile_url": profile_chat_url(
            display_profile,
            target,
        ),
        "demo": demo,
        "likes": likes,
        **_ranking_cache_context(
            cached,
            total_items=len(opportunities),
            total_units=total_openings,
        ),
        "item_singular": "opportunity",
        "item_plural": "opportunities",
        "unit_singular": "opening",
        "unit_plural": "openings",
        "region_filter_options": LABOR_MARKET_REGIONS,
        "show_license_filter": True,
        "filter_item_singular": "opportunity",
        "filter_item_plural": "opportunities",
        "saved_opportunity_ids": saved_opportunity_ids,
    }


def build_program_results_context(
    *,
    session: ChatSession,
    program_groups: list[dict],
    likes: list[str],
    dislikes: list[str],
    name: str | None,
    demo: bool,
) -> dict:
    """Build template context for personalized program results."""
    target = MatchTarget.PROGRAMS

    ranking_profile = build_profile_for_target(
        target,
        likes=likes,
        dislikes=dislikes,
    )

    display_profile = _prepare_results_session(
        session,
        target,
        name=name,
        likes=likes,
        dislikes=dislikes,
    )

    total_programs = sum_programs(program_groups)

    cached = session.ranking_cache.get(
        ranking_profile,
        target,
    )

    return {
        "profile": display_profile,
        "match_target": target.value,
        "chat_profile_url": profile_chat_url(
            display_profile,
            target,
        ),
        "demo": demo,
        "rank_stream_url": profile_url(
            "/api/rank-programs",
            ranking_profile,
        ),
        **_ranking_cache_context(
            cached,
            total_items=len(program_groups),
            total_units=total_programs,
        ),
        "item_singular": "career",
        "item_plural": "careers",
        "unit_singular": "registered program",
        "unit_plural": "registered programs",
        "region_filter_options": LABOR_MARKET_REGIONS,
        "show_license_filter": False,
        "filter_item_singular": "career",
        "filter_item_plural": "careers",
    }
