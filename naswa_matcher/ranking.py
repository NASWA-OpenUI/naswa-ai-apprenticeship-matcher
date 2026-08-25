from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from strands import Agent

from naswa_matcher.opportunity_detail import build_opportunity_summary

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


def build_onet_ranking_fields(onet: dict) -> dict:
    """Build the compact O*NET fields used as AI ranking evidence."""
    return {
        "description": (onet.get("description") or "")[:300],
        "skills": _pluck(
            _nested_list(onet, ("skills", "data", "element")),
            "name",
            5,
        ),
        "activities": _pluck(
            _nested_list(
                onet,
                ("detailed_work_activities", "data", "activity"),
            ),
            "title",
            5,
        ),
        "work_styles": _pluck(
            _nested_list(onet, ("work_styles", "data", "element")),
            "name",
            4,
        ),
    }


def normalize_tier(tier: str | None) -> str:
    """Keep unexpected model output from breaking CSS/classes/sorting."""
    if tier in TIER_ORDER:
        return tier

    return "Weak"


def build_job_summary(job: dict) -> dict:
    """Build the compact opportunity summary sent to the scoring model."""
    posting = job.get("posting", {})
    onet = job.get("onet") or {}

    return {
        "id": job["id"],
        "title": posting.get("jobTitle"),
        "requirements_summary": posting.get("requirementsSummary"),
        "transportation_requirement": posting.get("transportationRequirement"),
        **build_onet_ranking_fields(onet),
    }


def build_scoring_prompt(profile: dict, job_summaries: list[dict]) -> str:
    """Build the prompt used to score O*NET-backed opportunities."""

    scoring_profile = {
        "likes": list(profile.get("likes") or []),
        "dislikes": list(profile.get("dislikes") or []),
        "transportation": profile.get("transportation"),
    }

    return (
        "You are ranking New York State registered apprenticeship opportunities "
        "for the person who will read these results.\n\n"
        "Profile:\n"
        f"{json.dumps(scoring_profile, indent=2)}\n\n"
        "Score each job as Strong, Moderate, or Weak.\n\n"
        "Guidance:\n"
        "- Put the most weight on whether the occupation connects to the profile's likes.\n"
        "- Use dislikes only as a soft negative signal.\n"
        "- Use transportation only when the profile and the opportunity's transportation requirement provide relevant evidence.\n"
        "- A transportation concern can be a caveat, but do not reject a job only because a requirement may need to be checked later.\n"
        "- Do not reject a job only because a requirement may need to be checked later.\n"
        "- Keep explanations friendly and concrete.\n"
        "- Write every explanation directly to the person reading it.\n"
        "- Use second person: you, your.\n"
        "- Do not refer to the person as the user, the reader, the applicant, someone, they, or their.\n"
        '- Do not write phrases like "the user\'s interests", "the user has a car", "their interests", or "someone who drives".\n'
        '- It is okay to use "applicants" only when describing official program requirements.\n\n'
        "- Return ONLY a JSON array — no markdown, no extra text:\n"
        "- The JSON must contain exactly one object for every job ID provided.\n"
        "- Do not include trailing commas.\n"
        "- Do not omit jobs.\n"
        "- Do not invent job IDs.\n\n"
        '[{"id":"<id>","tier":"Strong|Moderate|Weak","explanation":"1-2 sentences addressed to you using you/your"}]\n\n'
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
) -> list[dict]:
    """Attach model scores back to jobs and sort this batch by rank."""
    score_map = {
        score.get("id"): score
        for score in scores
        if isinstance(score, dict) and score.get("id")
    }

    ranked = []

    for job in batch_jobs:
        score = score_map.get(job["id"], {})
        tier = normalize_tier(score.get("tier"))

        ranked.append(
            {
                "id": job["id"],
                "tier": tier,
                "tier_order": TIER_ORDER.get(tier, 3),
                "sort_index": job_index[job["id"]],
                "explanation": score.get("explanation", ""),
                "posting": job["posting"],
                "summary": build_opportunity_summary(job),
            }
        )

    return sort_ranked_items(ranked)


def sort_ranked_items(ranked: list[dict]) -> list[dict]:
    """Sort ranked items by tier and original order."""
    return sorted(
        ranked,
        key=lambda item: (
            item["tier_order"],
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
    summaries = [build_job_summary(job) for job in onet_jobs]
    prompt = build_scoring_prompt(profile, summaries)

    scorer = Agent(
        model=model_factory(),
        callback_handler=None,
    )

    result = await scorer.invoke_async(prompt)
    return parse_scoring_response(str(result))
