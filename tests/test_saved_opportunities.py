from naswa_matcher.saved_opportunities import (
    active_saved_opportunity_count,
    resolve_saved_opportunities,
)
from naswa_matcher.saves import SavedItems


def test_active_saved_opportunity_count_ignores_missing_items(monkeypatch):
    monkeypatch.setattr(
        "naswa_matcher.saved_opportunities.all_opportunities",
        lambda: [
            {"id": "one"},
            {"id": "two"},
        ],
    )

    saved = SavedItems(opportunity_ids=("one", "missing", "two"))

    assert active_saved_opportunity_count(saved) == 2


def test_resolve_saved_opportunities_separates_missing_items(
    monkeypatch,
):
    opportunities = [
        {
            "id": "zebra",
            "posting": {"jobTitle": "Zebra Worker"},
        },
        {
            "id": "apple",
            "posting": {"jobTitle": "Apple Worker"},
        },
    ]

    monkeypatch.setattr(
        "naswa_matcher.saved_opportunities.all_opportunities",
        lambda: opportunities,
    )

    monkeypatch.setattr(
        "naswa_matcher.saved_opportunities.build_opportunity_detail",
        lambda opportunity: {"id": opportunity["id"]},
    )

    saved = SavedItems(opportunity_ids=("zebra", "missing", "apple"))

    resolved = resolve_saved_opportunities(saved)

    assert resolved.available_ids == ("apple", "zebra")
    assert resolved.unavailable_ids == ("missing",)
    assert resolved.available_count == 2
    assert resolved.unavailable_count == 1
