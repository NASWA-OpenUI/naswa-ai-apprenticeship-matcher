from __future__ import annotations

import logging
import re

from naswa_matcher.location_data import location_terms

logger = logging.getLogger("naswa.location_matching")

NEARBY_LOCATION_GROUPS = {
    "western": {"finger_lakes", "southern_tier"},
    "finger_lakes": {"western", "southern_tier", "central"},
    "southern_tier": {"western", "finger_lakes", "central", "mohawk_valley"},
    "central": {"finger_lakes", "southern_tier", "mohawk_valley", "north_country"},
    "mohawk_valley": {"central", "southern_tier", "capital", "north_country"},
    "capital": {"mohawk_valley", "north_country", "hudson_valley"},
    "north_country": {"capital", "mohawk_valley", "central"},
    "hudson_valley": {"capital", "new_york_city", "long_island"},
    "new_york_city": {"hudson_valley", "long_island"},
    "long_island": {"new_york_city", "hudson_valley"},
}


LOCATION_FIT_ORDER = {
    "local": 0,
    "nearby": 1,
    "unknown": 2,
    "far": 3,
}


VALID_TIERS = {"Strong", "Moderate", "Weak"}


def should_use_location_matching(profile: dict) -> bool:
    """Return whether location/transportation should affect ranking."""
    value = profile.get("use_location_matching", True)

    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no"}

    return value is not False


def _term_match_spans(text: str, term: str) -> list[tuple[int, int]]:
    """Return full-word phrase match spans for a location term."""
    pattern = r"\b" + re.escape(term.lower()) + r"\b"
    return [(match.start(), match.end()) for match in re.finditer(pattern, text)]


def text_mentions_term(text: str, term: str) -> bool:
    """Return True if text contains term as a rough phrase match."""
    return bool(_term_match_spans(text.lower(), term))


def _format_region_keys(region_keys: set[str] | frozenset[str]) -> str:
    """Format region keys for readable logs."""
    return ", ".join(sorted(region_keys)) or "none"


def _format_match_details(matches: list[dict]) -> str:
    """Format matched location terms for readable logs."""
    parts = []
    seen = set()

    for match in matches:
        region_keys = tuple(sorted(match["region_keys"]))
        key = (match["term"], region_keys)

        if key in seen:
            continue

        seen.add(key)
        parts.append(f"{match['term']} -> {', '.join(region_keys)}")

    return "; ".join(parts) or "none"


def _infer_location_groups_with_matches(
    text: str | None,
) -> tuple[set[str], list[dict]]:
    """Infer location groups and keep the accepted term matches."""
    if not text:
        return set(), []

    normalized = text.lower()
    matches = []

    for location_term in location_terms():
        for start, end in _term_match_spans(normalized, location_term.term):
            matches.append(
                {
                    "term": location_term.term,
                    "start": start,
                    "end": end,
                    "region_keys": location_term.region_keys,
                }
            )

    # Prefer the longest match first. This is important for cases like:
    # "Long Island City" should match New York City, not both New York City
    # and Long Island.
    matches.sort(
        key=lambda match: (
            -(match["end"] - match["start"]),
            match["start"],
        )
    )

    groups = set()
    occupied_spans: list[tuple[int, int]] = []
    accepted_matches = []

    for match in matches:
        start = match["start"]
        end = match["end"]

        overlaps_existing_match = any(
            not (end <= occupied_start or start >= occupied_end)
            for occupied_start, occupied_end in occupied_spans
        )

        if overlaps_existing_match:
            continue

        groups.update(match["region_keys"])
        occupied_spans.append((start, end))
        accepted_matches.append(match)

    return groups, accepted_matches


def infer_location_groups(text: str | None) -> set[str]:
    """Infer NY labor market region groups from user text or posting text."""
    groups, _matches = _infer_location_groups_with_matches(text)
    return groups


def log_user_location_inference(location: str | None) -> None:
    """Log how a user's stated location maps to NY labor market regions."""
    if not location:
        return

    groups, matches = _infer_location_groups_with_matches(location)

    logger.info(
        "User location inference location=%r; groups=%s; matches=%s",
        location,
        _format_region_keys(groups),
        _format_match_details(matches),
    )


def job_location_text(job: dict) -> str:
    """Build one searchable location string from the posting's real location fields."""
    posting = job.get("posting", {})

    location_summary = posting.get("locationSummary") or ""

    regions = posting.get("regions") or []
    if isinstance(regions, list):
        regions_text = " ".join(str(region) for region in regions)
    else:
        regions_text = str(regions)

    all_requirements = posting.get("allRequirements") or []
    if isinstance(all_requirements, list):
        requirements_text = " ".join(
            str(requirement) for requirement in all_requirements
        )
    else:
        requirements_text = str(all_requirements)

    return " ".join(
        [
            location_summary,
            regions_text,
            requirements_text,
        ]
    )


def location_fit(profile: dict, job: dict) -> str:
    """
    Return a rough location fit:
    - local: job appears to include the user's region
    - nearby: job appears to include a neighboring region
    - far: known user/job regions do not overlap
    - unknown: not enough info
    """
    user_groups = infer_location_groups(profile.get("location"))
    job_groups = infer_location_groups(job_location_text(job))

    if not user_groups or not job_groups:
        return "unknown"

    if user_groups & job_groups:
        return "local"

    nearby_groups = set()
    for group in user_groups:
        nearby_groups.update(NEARBY_LOCATION_GROUPS.get(group, set()))

    if nearby_groups & job_groups:
        return "nearby"

    return "far"


def cap_tier_by_location(tier: str | None, location_fit: str) -> str:
    """Prevent far-away jobs from being ranked as Strong."""
    if tier not in VALID_TIERS:
        tier = "Weak"

    if location_fit in {"nearby", "far"} and tier == "Strong":
        return "Moderate"

    return tier
