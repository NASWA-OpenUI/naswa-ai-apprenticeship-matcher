from datetime import date

import pytest

from naswa_matcher.opportunity_detail import (
    _application_chip_label,
    _application_fee,
    _format_application_range,
    _format_chip_date,
    _license_required,
    build_opportunity_detail,
    build_opportunity_summary,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        (0, None),
        ("0", None),
        (-1, None),
        ("-1", None),
        (10, 10),
        ("10", 10),
        (20, 20),
        ("20", 20),
        (50, 50),
        ("50", 50),
        ("not a number", None),
    ],
)
def test_application_fee_returns_positive_integer_or_none(value, expected):
    """Verifies that application fees are normalized to positive integers and
    blank, zero, negative, or invalid values are treated as no fee."""
    assert _application_fee(value) == expected


@pytest.mark.parametrize(
    ("transportation_requirement", "expected"),
    [
        (None, False),
        ("", False),
        ("Must have reliable transportation.", False),
        (
            "Must have a valid driver's license and reliable transportation.",
            True,
        ),
        (
            "Must have a valid New York State driver’s license to operate company vehicles.",
            True,
        ),
        (
            "Must possess a valid NYS driver's license.",
            True,
        ),
        (
            "Must have a valid DRIVER'S LICENSE and reliable transportation.",
            True,
        ),
    ],
)
def test_license_required_checks_transportation_requirement(
    transportation_requirement,
    expected,
):
    """Verifies that driver's license requirements are derived from the
    transportationRequirement text using the wording that appears in the data."""
    posting = {"transportationRequirement": transportation_requirement}

    assert _license_required(posting) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2026, 6, 29), "Jun 29, 2026"),
        (date(2026, 7, 1), "Jul 1, 2026"),
        (date(2026, 12, 31), "Dec 31, 2026"),
    ],
)
def test_format_chip_date(value, expected):
    """Verifies that chip dates are formatted in the compact month/day/year
    style used by the opportunity detail page."""
    assert _format_chip_date(value) == expected


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (
            date(2026, 7, 1),
            date(2026, 7, 31),
            "Jul 1–31, 2026",
        ),
        (
            date(2026, 6, 29),
            date(2026, 7, 31),
            "Jun 29–Jul 31, 2026",
        ),
        (
            date(2026, 12, 1),
            date(2027, 1, 31),
            "Dec 1, 2026–Jan 31, 2027",
        ),
    ],
)
def test_format_application_range(start, end, expected):
    """Verifies that application date ranges collapse repeated months/years
    while still showing enough context for cross-month or cross-year ranges."""
    assert _format_application_range(start, end) == expected


@pytest.mark.parametrize(
    ("today", "start", "end", "expected"),
    [
        (
            date(2026, 6, 25),
            "2026-07-01",
            "2026-07-31",
            "Apply Jul 1–31, 2026",
        ),
        (
            date(2026, 6, 25),
            "2026-06-01",
            "2026-06-29",
            "Apply by Jun 29, 2026",
        ),
        (
            date(2026, 6, 1),
            "2026-06-01",
            "2026-06-29",
            "Apply by Jun 29, 2026",
        ),
        (
            date(2026, 6, 29),
            "2026-06-01",
            "2026-06-29",
            "Apply by Jun 29, 2026",
        ),
        (
            date(2026, 7, 1),
            "2026-06-01",
            "2026-06-30",
            "Applications closed Jun 30, 2026",
        ),
        (
            date(2026, 6, 25),
            "2026-12-01",
            "2027-01-31",
            "Apply Dec 1, 2026–Jan 31, 2027",
        ),
    ],
)
def test_application_chip_label(today, start, end, expected):
    """Verifies that the application chip label changes correctly for future,
    open, boundary-day, and closed application periods."""
    assert (
        _application_chip_label(
            start,
            end,
            today=today,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (None, "2026-06-30"),
        ("2026-06-01", None),
        (None, None),
        ("bad-date", "2026-06-30"),
        ("2026-06-01", "bad-date"),
    ],
)
def test_application_chip_label_returns_none_for_missing_or_invalid_dates(
    start,
    end,
):
    """Verifies that missing or invalid application dates do not produce a chip
    label, rather than raising an error or displaying misleading text."""
    assert _application_chip_label(start, end, today=date(2026, 6, 25)) is None


def make_opp(
    *,
    start: str = "2026-06-01",
    end: str = "2026-06-29",
    fee=None,
    openings=10,
    transportation="Must have a valid driver's license.",
    source_url="https://dol.ny.gov/example",
) -> dict:
    """Builds a minimal opportunity fixture for testing detail-page derived
    values without depending on full JSON opportunity files."""
    return {
        "posting": {
            "applicationStartDate": start,
            "applicationEndDate": end,
            "applicationFee": fee,
            "numberOfOpenings": openings,
            "transportationRequirement": transportation,
            "sourceUrl": source_url,
        }
    }


def test_build_opportunity_summary_returns_card_and_detail_facts():
    """Verifies that reusable opportunity summary facts are derived from the
    posting fields used by both ranked cards and detail pages."""
    summary = build_opportunity_summary(
        make_opp(
            fee="25",
            openings=4,
            transportation="Must have a valid driver's license.",
        )
    )

    assert summary == {
        "number_of_openings": 4,
        "application_fee": 25,
        "license_required": True,
    }


def test_build_opportunity_summary_hides_missing_fee_and_license():
    """Verifies that blank fees and transportation-only requirements do not
    produce fee or license indicators."""
    summary = build_opportunity_summary(
        make_opp(
            fee="",
            openings=8,
            transportation="Must have reliable transportation to job sites and classes.",
        )
    )

    assert summary == {
        "number_of_openings": 8,
        "application_fee": None,
        "license_required": False,
    }


def test_build_opportunity_summary_handles_missing_posting():
    """Verifies that a malformed/minimal opportunity does not raise while
    deriving summary values."""
    summary = build_opportunity_summary({})

    assert summary == {
        "number_of_openings": None,
        "application_fee": None,
        "license_required": False,
    }


def test_build_opportunity_detail_for_open_application_period():
    """Verifies that build_opportunity_detail returns the expected template
    fields for an opportunity whose application period is currently open."""
    detail = build_opportunity_detail(
        make_opp(fee="20"),
        today=date(2026, 6, 25),
    )

    assert detail == {
        "application_start_date": "2026-06-01",
        "application_end_date": "2026-06-29",
        "application_chip_label": "Apply by Jun 29, 2026",
        "number_of_openings": 10,
        "application_fee": 20,
        "license_required": True,
        "source_url": "https://dol.ny.gov/example",
        "apply_url": "#",
        "bottom_apply_note": "$20 application fee · Apply by Jun 29, 2026",
    }


def test_build_opportunity_detail_for_future_application_period():
    """Verifies that future application periods are labelled with the upcoming
    application range and still include fee/license-derived details."""
    detail = build_opportunity_detail(
        make_opp(
            start="2026-07-01",
            end="2026-07-31",
            fee=25,
            transportation="Must have reliable transportation.",
        ),
        today=date(2026, 6, 25),
    )

    assert detail["application_chip_label"] == "Apply Jul 1–31, 2026"
    assert detail["application_fee"] == 25
    assert detail["license_required"] is False
    assert detail["bottom_apply_note"] == "$25 application fee · Apply Jul 1–31, 2026"


def test_build_opportunity_detail_for_closed_application_period():
    """Verifies that closed application periods are labelled as closed and that
    the bottom apply note does not include a missing application fee."""
    detail = build_opportunity_detail(
        make_opp(
            start="2026-06-01",
            end="2026-06-30",
            fee=None,
        ),
        today=date(2026, 7, 1),
    )

    assert detail["application_chip_label"] == "Applications closed Jun 30, 2026"
    assert detail["application_fee"] is None
    assert detail["bottom_apply_note"] == "Applications closed Jun 30, 2026"


@pytest.mark.parametrize("fee", [None, "", 0, "0"])
def test_build_opportunity_detail_hides_blank_or_zero_application_fee(fee):
    """Verifies that blank or zero application fees are hidden from the derived
    detail values and bottom apply note."""
    detail = build_opportunity_detail(
        make_opp(fee=fee),
        today=date(2026, 6, 25),
    )

    assert detail["application_fee"] is None
    assert "$0 application fee" not in detail["bottom_apply_note"]
    assert detail["bottom_apply_note"] == "Apply by Jun 29, 2026"
