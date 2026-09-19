from dataclasses import dataclass

from naswa_matcher.db import all_opportunities
from naswa_matcher.opportunity_detail import build_opportunity_detail
from naswa_matcher.saves import SavedItems


@dataclass(frozen=True)
class ResolvedSavedOpportunities:
    """Saved opportunities resolved against the current dataset."""

    available: list[dict]
    unavailable_ids: tuple[str, ...]

    @property
    def available_count(self) -> int:
        return len(self.available)

    @property
    def unavailable_count(self) -> int:
        return len(self.unavailable_ids)

    @property
    def available_ids(self) -> tuple[str, ...]:
        return tuple(item["opportunity"]["id"] for item in self.available)


def _opportunities_by_id() -> dict[str, dict]:
    """Return current opportunities keyed by opportunity ID."""
    return {str(opportunity["id"]): opportunity for opportunity in all_opportunities()}


def active_saved_opportunity_count(saved: SavedItems) -> int:
    """Return the number of saved opportunities still in the current dataset."""
    opportunities_by_id = _opportunities_by_id()

    return sum(
        opportunity_id in opportunities_by_id
        for opportunity_id in saved.opportunity_ids
    )


def resolve_saved_opportunities(
    saved: SavedItems,
) -> ResolvedSavedOpportunities:
    """Resolve saved opportunity IDs against the current dataset."""
    opportunities_by_id = _opportunities_by_id()

    available = []
    unavailable_ids = []

    for opportunity_id in saved.opportunity_ids:
        opportunity = opportunities_by_id.get(opportunity_id)

        if opportunity is None:
            unavailable_ids.append(opportunity_id)
            continue

        available.append(
            {
                "opportunity": opportunity,
                "detail": build_opportunity_detail(opportunity),
            }
        )

    available.sort(
        key=lambda item: (
            item["opportunity"].get("posting", {}).get("jobTitle", "").casefold()
        )
    )

    return ResolvedSavedOpportunities(
        available=available,
        unavailable_ids=tuple(unavailable_ids),
    )
