from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from strands import Agent

from naswa_matcher.location_matching import (
    LOCATION_FIT_ORDER,
    cap_tier_by_location,
    location_fit,
    should_use_location_matching,
)

ModelFactory = Callable[[], Any]

TIER_ORDER = {"Strong": 0, "Moderate": 1, "Weak": 2}


def _nested_list(data: dict, path: tuple[str, ...]) -> list:
    """Safely read a nested list from O*NET data."""
    value: object = data

    for key in path:
        if not isinstance(value, dict):
            return []
        value = value.get(key)

    return value if isinstance(value, list) else []


def _pluck(items: list, field: str, limit: int) -> list[str]:
    """Return up to `limit` string values from a list of dicts."""
    values = []

    for item in items[:limit]:
        if not isinstance(item, dict):
            continue

        value = item.get(field)
        if value:
            values.append(str(value))

    return values


def normalize_tier(tier: str | None) -> str:
    """Keep unexpected model output from breaking CSS/classes/sorting."""
    if tier in TIER_ORDER:
        return tier

    return "Weak"


def build_job_summary(profile: dict, job: dict) -> dict:
    """Build the compact job summary sent to the scoring model."""
    posting = job.get("posting", {})
    onet = job.get("onet") or {}

    skills = _pluck(
        _nested_list(onet, ("skills", "data", "element")),
        "name",
        5,
    )
    activities = _pluck(
        _nested_list(onet, ("detailed_work_activities", "data", "activity")),
        "title",
        5,
    )
    styles = _pluck(
        _nested_list(onet, ("work_styles", "data", "element")),
        "name",
        4,
    )

    summary = {
        "id": job["id"],
        "title": posting.get("jobTitle"),
        "location": posting.get("locationSummary"),
        "regions": posting.get("regions", []),
        "requirements_summary": posting.get("requirementsSummary"),
        "description": (onet.get("description") or "")[:300],
        "skills": skills,
        "activities": activities,
        "work_styles": styles,
    }

    if should_use_location_matching(profile):
        summary["location_fit"] = location_fit(profile, job)
        summary["transportation_requirement"] = posting.get("transportationRequirement")

    return summary


def build_scoring_prompt(profile: dict, job_summaries: list[dict]) -> str:
    """Build the prompt used to score O*NET-backed opportunities."""

    def get_location_guidance(use_location_matching: bool) -> str:
        if use_location_matching:
            return (
                "- Location is a major ranking factor, not a minor detail.\n"
                "- A job should only be Strong if it fits both the user's interests and their location.\n"
                "- If location_fit is far, do not rank the job as Strong.\n"
                "- If location_fit is nearby, usually rank the job as Moderate.\n"
                "- Having a car helps with local travel, but it does not make a job across New York State feasible.\n"
                "- Do not describe a long-distance commute as feasible just because the user has a car.\n"
                "- If transportation or location may be an issue, mention it gently as a caveat.\n"
            )

        return (
            "- Do not use location or transportation as ranking factors for this user.\n"
            "- Do not mention the user's statewide flexibility in every explanation.\n"
        )

    return (
        "You are ranking New York State registered apprenticeship opportunities "
        "for a user based on a short derived profile.\n\n"
        "User profile:\n"
        f"{json.dumps(profile, indent=2)}\n\n"
        "Score each job as Strong, Moderate, or Weak.\n\n"
        "Guidance:\n"
        "- Put the most weight on whether the occupation connects to the user's likes.\n"
        f"{get_location_guidance(should_use_location_matching(profile))}"
        "- Use dislikes only as a soft negative signal.\n"
        "- Do not reject a job only because a requirement may need to be checked later.\n"
        "- Keep explanations friendly and concrete.\n\n"
        "- Return ONLY a JSON array — no markdown, no extra text:\n"
        "- The JSON must contain exactly one object for every job ID provided.\n"
        "- Do not include trailing commas.\n"
        "- Do not omit jobs.\n"
        "- Do not invent job IDs.\n\n"
        '[{"id":"<id>","tier":"Strong|Moderate|Weak","explanation":"1-2 sentences why"}]\n\n'
        f"Jobs:\n{json.dumps(job_summaries, indent=2)}"
    )


def parse_scoring_response(raw: str) -> list[dict]:
    """Parse the model's JSON array response, tolerating markdown fences."""
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        cleaned = match.group()

    parsed = json.loads(cleaned)

    if not isinstance(parsed, list):
        raise ValueError("Scoring response was not a JSON array.")

    return parsed


def build_ranked_items(
    batch_jobs: list[dict],
    scores: list[dict],
    job_index: dict[str, int],
    profile: dict,
) -> list[dict]:
    """Attach model scores back to jobs and sort this batch by rank."""
    score_map = {
        score.get("id"): score
        for score in scores
        if isinstance(score, dict) and score.get("id")
    }

    ranked = []
    use_location_matching = should_use_location_matching(profile)

    for job in batch_jobs:
        score = score_map.get(job["id"], {})
        model_tier = normalize_tier(score.get("tier"))
        job_location_fit = location_fit(profile, job) if use_location_matching else None

        tier = (
            cap_tier_by_location(model_tier, job_location_fit)
            if use_location_matching
            else model_tier
        )

        ranked.append(
            {
                "id": job["id"],
                "tier": tier,
                "tier_order": TIER_ORDER.get(tier, 3),
                "sort_index": job_index[job["id"]],
                "location_fit": job_location_fit,
                "explanation": score.get("explanation", ""),
                "posting": job["posting"],
            }
        )

    return sort_ranked_items(ranked, profile)


def sort_ranked_items(ranked: list[dict], profile: dict) -> list[dict]:
    """Sort ranked opportunities by tier, location fit, and original order."""
    use_location_matching = should_use_location_matching(profile)

    return sorted(
        ranked,
        key=lambda item: (
            item["tier_order"],
            (
                LOCATION_FIT_ORDER.get(item.get("location_fit"), 9)
                if use_location_matching
                else 0
            ),
            item["sort_index"],
        ),
    )


async def score_jobs(
    profile: dict,
    onet_jobs: list[dict],
    *,
    model_factory: ModelFactory,
) -> list[dict]:
    """Score O*NET-backed jobs against a user profile."""
    summaries = [build_job_summary(profile, job) for job in onet_jobs]
    prompt = build_scoring_prompt(profile, summaries)

    scorer = Agent(
        model=model_factory(),
        callback_handler=None,
    )

    result = await scorer.invoke_async(prompt)
    return parse_scoring_response(str(result))
