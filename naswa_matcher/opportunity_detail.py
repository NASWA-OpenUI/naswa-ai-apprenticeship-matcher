from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _application_fee(value) -> int | None:
    """Return a positive application fee, or None when blank/free/missing."""
    if value is None or value == "":
        return None

    try:
        fee = int(value)
    except TypeError, ValueError:
        return None

    return fee if fee > 0 else None


def _license_required(posting: dict) -> bool:
    """Return whether the posting mentions a driver's license requirement."""
    transportation_requirement = posting.get("transportationRequirement") or ""
    return "license" in transportation_requirement.lower()


def _today_in_new_york() -> date:
    """Return today's date in New York time for application-period comparisons."""
    return datetime.now(ZoneInfo("America/New_York")).date()


def _parse_iso_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD into a date, returning None for missing or invalid values."""
    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _format_chip_date(value: date) -> str:
    """Format a date for compact chip text, e.g. Jun 29, 2026."""
    return f"{_MONTHS[value.month - 1][:3]} {value.day}, {value.year}"


def _format_application_range(start: date, end: date) -> str:
    """Format a compact application date range for chip text."""
    start_month = _MONTHS[start.month - 1][:3]
    end_month = _MONTHS[end.month - 1][:3]

    if start.year == end.year and start.month == end.month:
        return f"{start_month} {start.day}–{end.day}, {end.year}"

    if start.year == end.year:
        return f"{start_month} {start.day}–{end_month} {end.day}, {end.year}"

    return f"{start_month} {start.day}, {start.year}–{end_month} {end.day}, {end.year}"


def _application_chip_label(
    start_value: str | None,
    end_value: str | None,
    *,
    today: date | None = None,
) -> str | None:
    """Return the application-period chip text for a single opportunity."""
    start = _parse_iso_date(start_value)
    end = _parse_iso_date(end_value)

    if not start or not end:
        return None

    today = today or _today_in_new_york()

    if today < start:
        return f"Apply {_format_application_range(start, end)}"

    if today <= end:
        return f"Apply by {_format_chip_date(end)}"

    return f"Applications closed {_format_chip_date(end)}"


def build_opportunity_summary(opp: dict) -> dict:
    """Build small reusable summary facts for opportunity cards and detail pages."""
    posting = opp.get("posting", {})

    return {
        "number_of_openings": posting.get("numberOfOpenings"),
        "application_fee": _application_fee(posting.get("applicationFee")),
        "license_required": _license_required(posting),
    }


def build_opportunity_detail(
    opp: dict,
    *,
    today: date | None = None,
) -> dict:
    """Build template-friendly values for the single-opportunity detail page."""
    posting = opp.get("posting", {})

    application_start_date = posting.get("applicationStartDate")
    application_end_date = posting.get("applicationEndDate")

    application_chip_label = _application_chip_label(
        application_start_date,
        application_end_date,
        today=today,
    )

    opportunity_summary = build_opportunity_summary(opp)
    application_fee = opportunity_summary["application_fee"]

    bottom_apply_parts = []

    if application_fee:
        bottom_apply_parts.append(f"${application_fee} application fee")

    if application_chip_label:
        bottom_apply_parts.append(application_chip_label)

    return {
        "application_start_date": application_start_date,
        "application_end_date": application_end_date,
        "application_chip_label": application_chip_label,
        "number_of_openings": opportunity_summary["number_of_openings"],
        "application_fee": application_fee,
        "license_required": opportunity_summary["license_required"],
        "source_url": posting.get("sourceUrl"),
        "apply_url": "#",
        "bottom_apply_note": " · ".join(bottom_apply_parts),
    }
