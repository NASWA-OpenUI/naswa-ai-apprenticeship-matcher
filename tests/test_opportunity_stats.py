import pytest

from naswa_matcher.opportunity_stats import opening_count, sum_openings


@pytest.mark.parametrize(
    ("opportunity", "expected"),
    [
        ({"posting": {"numberOfOpenings": 3}}, 3),
        ({"posting": {"numberOfOpenings": "12"}}, 12),
        ({"posting": {"numberOfOpenings": 0}}, 0),
        ({"posting": {"numberOfOpenings": "0"}}, 0),
    ],
)
def test_opening_count_returns_valid_opening_count(opportunity, expected):
    """Return the opening count when numberOfOpenings is a valid integer-like value."""
    assert opening_count(opportunity) == expected


@pytest.mark.parametrize(
    "opportunity",
    [
        {},
        {"posting": {}},
        {"posting": {"numberOfOpenings": None}},
        {"posting": {"numberOfOpenings": ""}},
        {"posting": {"numberOfOpenings": "not-a-number"}},
    ],
)
def test_opening_count_returns_zero_for_missing_or_invalid_values(opportunity):
    """Return zero when numberOfOpenings is missing, blank, null, or invalid."""
    assert opening_count(opportunity) == 0


@pytest.mark.parametrize(
    ("opportunity", "expected"),
    [
        ({"posting": {"numberOfOpenings": -1}}, 0),
        ({"posting": {"numberOfOpenings": "-5"}}, 0),
    ],
)
def test_opening_count_clamps_negative_values_to_zero(opportunity, expected):
    """Clamp negative opening counts to zero."""
    assert opening_count(opportunity) == expected


def test_sum_openings_adds_openings_across_opportunities():
    """Add valid opening counts across multiple opportunities."""
    opportunities = [
        {"posting": {"numberOfOpenings": 3}},
        {"posting": {"numberOfOpenings": 12}},
        {"posting": {"numberOfOpenings": "5"}},
    ]

    assert sum_openings(opportunities) == 20


def test_sum_openings_treats_invalid_values_as_zero():
    """Ignore invalid, missing, null, and negative opening counts when summing."""
    opportunities = [
        {"posting": {"numberOfOpenings": 3}},
        {"posting": {"numberOfOpenings": None}},
        {"posting": {"numberOfOpenings": "not-a-number"}},
        {"posting": {}},
        {},
        {"posting": {"numberOfOpenings": -10}},
    ]

    assert sum_openings(opportunities) == 3


def test_sum_openings_returns_zero_for_empty_list():
    """Return zero when there are no opportunities to sum."""
    assert sum_openings([]) == 0
