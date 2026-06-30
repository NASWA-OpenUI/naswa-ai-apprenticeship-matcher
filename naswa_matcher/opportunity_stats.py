def opening_count(opportunity: dict) -> int:
    """Return a safe integer opening count for one opportunity."""
    value = opportunity.get("posting", {}).get("numberOfOpenings")

    try:
        openings = int(value)
    except TypeError, ValueError:
        return 0

    return max(0, openings)


def sum_openings(opportunities: list[dict]) -> int:
    """Return total openings across opportunities."""
    return sum(opening_count(opportunity) for opportunity in opportunities)
