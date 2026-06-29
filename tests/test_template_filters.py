import pytest

from naswa_matcher.template_filters import (
    TEMPLATE_FILTERS,
    format_date,
    format_wage,
    percent_of,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-06-29", "June 29, 2026"),
        ("2026-01-01", "January 1, 2026"),
        ("2026-12-31", "December 31, 2026"),
        (None, "—"),
        ("", "—"),
    ],
)
def test_format_date_formats_valid_dates(value, expected):
    assert format_date(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "not-a-date",
        "2026-13-01",
        "2026-06-nope",
        "2026-06-29-extra",
        "2026-00-01"
    ],
)
def test_format_date_returns_original_value_for_invalid_dates(value):
    assert format_date(value) == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (59092, "$59,092"),
        (59092.4, "$59,092"),
        (59092.6, "$59,093"),
        (0, "$0"),
        (None, "—"),
    ],
)
def test_format_wage(value, expected):
    assert format_wage(value) == expected


@pytest.mark.parametrize(
    ("value", "maximum", "expected"),
    [
        (50, 100, 50),
        (59_092, 98_200, 60),
        (78_450, 98_200, 80),
        (98_200, 98_200, 100),
        (150, 100, 100),
        (-10, 100, 0),
        (50, 0, 0),
        (50, -100, 0),
        (None, 100, 0),
        (50, None, 0),
        ("not-a-number", 100, 0),
        (50, "not-a-number", 0),
    ],
)
def test_percent_of(value, maximum, expected):
    assert percent_of(value, maximum) == expected


def test_template_filters_exports_expected_filters():
    assert TEMPLATE_FILTERS == {
        "format_date": format_date,
        "format_wage": format_wage,
        "percent_of": percent_of,
    }