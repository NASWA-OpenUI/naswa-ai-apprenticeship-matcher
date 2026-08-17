from __future__ import annotations

from naswa_matcher.location_matching import (
    location_fit_for_regions,
    should_use_location_matching,
)
from naswa_matcher.ranking import build_onet_ranking_fields


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


def build_program_summary(profile: dict, program_group: dict) -> dict:
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
        "regions": program_group.get("regions", []),
        "onet_description": onet_fields["description"],
        "skills": onet_fields["skills"],
        "activities": onet_fields["activities"],
        "work_styles": onet_fields["work_styles"],
        "trades": trades,
    }

    if should_use_location_matching(profile):
        summary["location_fit"] = location_fit_for_regions(
            profile,
            program_group.get("regions"),
        )

    return summary
