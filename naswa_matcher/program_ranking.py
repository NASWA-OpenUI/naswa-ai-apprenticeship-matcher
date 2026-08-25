from __future__ import annotations

import json

from strands import Agent

from naswa_matcher.ranking import (
    TIER_ORDER,
    ModelFactory,
    build_onet_ranking_fields,
    normalize_tier,
    parse_scoring_response,
    sort_ranked_items,
)


def sum_programs(program_groups: list[dict]) -> int:
    """Return the number of registered programs represented by SOC groups."""
    return sum(int(group.get("programCount") or 0) for group in program_groups)


def program_group_title(program_group: dict) -> str:
    """Return the display title for one SOC-grouped program result."""
    trades = [
        trade for trade in program_group.get("trades", []) if isinstance(trade, dict)
    ]

    if len(trades) == 1:
        trade = trades[0]

        return (
            trade.get("displayTradeName")
            or trade.get("tradeName")
            or program_group.get("socTitle")
            or program_group["socCode"]
        )

    return (
        program_group.get("socTitle")
        or (program_group.get("onet") or {}).get("title")
        or program_group["socCode"]
    )


def build_program_summary(program_group: dict) -> dict:
    """Build the compact SOC-group summary sent to the scoring model."""
    onet = program_group.get("onet") or {}
    onet_fields = build_onet_ranking_fields(onet)

    trades = []

    for trade in program_group.get("trades", []):
        if not isinstance(trade, dict):
            continue

        trade_name = trade.get("displayTradeName") or trade.get("tradeName")

        if not trade_name:
            continue

        trades.append(
            {
                "trade_name": trade_name,
                "description": trade.get("description") or "",
            }
        )

    summary = {
        "id": program_group["socCode"],
        "title": program_group_title(program_group),
        "soc_title": program_group.get("socTitle"),
        "onet_description": onet_fields["description"],
        "skills": onet_fields["skills"],
        "activities": onet_fields["activities"],
        "work_styles": onet_fields["work_styles"],
        "trades": trades,
    }

    return summary


def build_program_scoring_prompt(
    profile: dict,
    program_summaries: list[dict],
) -> str:
    """Build the prompt used to score SOC-grouped apprenticeship programs."""
    scoring_profile = {
        "likes": list(profile.get("likes") or []),
        "dislikes": list(profile.get("dislikes") or []),
    }

    return (
        "You are ranking New York State registered apprenticeship career groups "
        "for the person who will read these results.\n\n"
        "Each item represents one O*NET-SOC occupation group. A group may contain "
        "one or more apprenticeship trade titles.\n\n"
        "Profile:\n"
        f"{json.dumps(scoring_profile, indent=2)}\n\n"
        "Score each career group as Strong, Moderate, or Weak.\n\n"
        "Guidance:\n"
        "- Put the most weight on whether the occupation connects to the "
        "profile's likes.\n"
        "- Use both the O*NET occupation evidence and the individual trade "
        "descriptions when judging fit.\n"
        "- Trade descriptions are supporting evidence for the SOC group. "
        "Do not assume every trade within a group is identical.\n"
        "- Use dislikes only as a soft negative signal.\n"
        "- Keep explanations friendly and concrete.\n"
        "- Write every explanation directly to the person reading it.\n"
        "- Use second person: you, your.\n"
        "- Do not refer to the person as the user, reader, applicant, someone, "
        "they, or their.\n\n"
        "- Return ONLY a JSON array — no markdown, no extra text.\n"
        "- The JSON must contain exactly one object for every ID provided.\n"
        "- Do not omit groups.\n"
        "- Do not invent IDs.\n\n"
        '[{"id":"<id>","tier":"Strong|Moderate|Weak",'
        '"explanation":"1-2 sentences addressed to you using you/your"}]\n\n'
        f"Career groups:\n{json.dumps(program_summaries, indent=2)}"
    )


async def score_program_groups(
    profile: dict,
    program_groups: list[dict],
    *,
    model_factory: ModelFactory,
) -> list[dict]:
    """Score SOC-grouped registered apprenticeship programs."""
    summaries = [build_program_summary(group) for group in program_groups]

    prompt = build_program_scoring_prompt(
        profile,
        summaries,
    )

    scorer = Agent(
        model=model_factory(),
        callback_handler=None,
    )

    result = await scorer.invoke_async(prompt)

    return parse_scoring_response(str(result))


def build_ranked_program_items(
    batch_groups: list[dict],
    scores: list[dict],
    group_index: dict[str, int],
) -> list[dict]:
    """Attach model scores to SOC groups and sort one ranking batch."""
    score_map = {
        score.get("id"): score
        for score in scores
        if isinstance(score, dict) and score.get("id")
    }

    ranked = []

    for group in batch_groups:
        soc_code = group["socCode"]
        score = score_map.get(soc_code, {})
        tier = normalize_tier(score.get("tier"))

        ranked.append(
            {
                "id": soc_code,
                "title": program_group_title(group),
                "tier": tier,
                "tier_order": TIER_ORDER.get(tier, 3),
                "sort_index": group_index[soc_code],
                "explanation": score.get("explanation", ""),
                "program_group": group,
            }
        )

    return sort_ranked_items(ranked)
