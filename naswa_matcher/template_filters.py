from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from markdown_it import MarkdownIt
from markupsafe import Markup

_MARKDOWN = MarkdownIt("js-default").disable("image")
_NEW_YORK_TZ = ZoneInfo("America/New_York")


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


def chat_markdown(value: str | None) -> Markup:
    """Render safe, limited Markdown for chat messages."""
    rendered = _MARKDOWN.render(value or "")
    return Markup(rendered)


def format_date(iso: str | None) -> str:
    if not iso:
        return "—"

    try:
        y, m, d = iso.split("-")
        month = int(m)
        if month < 1 or month > 12:
            return iso
        return f"{_MONTHS[month - 1]} {int(d)}, {y}"
    except ValueError, IndexError:
        return iso


def format_wage(n: float | None) -> str:
    if n is None:
        return "—"

    return "$" + f"{round(n):,}"


def percent_of(value: float | None, maximum: float | None) -> int:
    """Return value as a clamped percentage of maximum."""
    try:
        value = float(value)
        maximum = float(maximum)
    except TypeError, ValueError:
        return 0

    if maximum <= 0:
        return 0

    return max(0, min(100, round(value / maximum * 100)))


def typical_program_length(programs: list[dict] | None) -> int | None:
    """Return the most common numeric program length, preferring shorter ties."""
    lengths = []

    for program in programs or []:
        value = program.get("programLength")

        if value in (None, ""):
            continue

        try:
            lengths.append(int(value))
        except TypeError, ValueError:
            continue

    if not lengths:
        return None

    counts = Counter(lengths)
    highest_count = max(counts.values())

    return min(length for length, count in counts.items() if count == highest_count)


def _new_york_today() -> date:
    """Return today's date in New York."""
    return datetime.now(_NEW_YORK_TZ).date()


def _parse_iso_date(value: object) -> date | None:
    """Return an ISO date value, or None when the value is missing or invalid."""
    if not isinstance(value, str) or not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _opportunity_is_hiring(opportunity: dict, today: date) -> bool:
    """Return whether an opportunity is current or upcoming.

    An opportunity counts as hiring until its application end date has passed.
    Its application start date is deliberately not checked so upcoming
    recruitment is included.
    """
    application_end_date = _parse_iso_date(opportunity.get("applicationEndDate"))

    return application_end_date is not None and application_end_date >= today


def _opportunity_matches_program(
    opportunity: dict,
    program: dict,
) -> bool:
    """Return whether an opportunity role belongs to the program occupation."""
    program_soc_code = str(program.get("socCode") or "").strip()
    opportunity_soc_code = str(opportunity.get("socCode") or "").strip()

    if not program_soc_code or not opportunity_soc_code:
        return True

    return program_soc_code == opportunity_soc_code


def _opportunity_openings(opportunity: dict) -> int:
    """Return a safe non-negative opening count for one opportunity."""
    try:
        openings = int(opportunity.get("numberOfOpenings") or 0)
    except TypeError, ValueError:
        return 0

    return max(openings, 0)


def program_hiring_stats(
    program_group: dict | None,
    *,
    today: date | None = None,
) -> dict:
    """Return current/upcoming hiring information for one program SOC group."""
    today = today or _new_york_today()

    hiring_program_keys = set()
    counted_opportunity_keys = set()

    hiring_trade_names = []
    seen_hiring_trade_names = set()

    open_positions = 0

    trades = (program_group or {}).get("trades") or []

    for trade_index, trade in enumerate(trades):
        if not isinstance(trade, dict):
            continue

        trade_is_hiring = False
        programs = trade.get("programs") or []

        for program_index, program in enumerate(programs):
            if not isinstance(program, dict):
                continue

            program_is_hiring = False
            opportunities = program.get("opportunities") or []

            for opportunity_index, opportunity in enumerate(opportunities):
                if not isinstance(opportunity, dict):
                    continue

                if not _opportunity_matches_program(opportunity, program):
                    continue

                if not _opportunity_is_hiring(opportunity, today):
                    continue

                program_is_hiring = True
                trade_is_hiring = True

                opportunity_id = opportunity.get("id")

                if opportunity_id not in (None, ""):
                    opportunity_key = ("id", str(opportunity_id))
                else:
                    opportunity_key = (
                        "position",
                        trade_index,
                        program_index,
                        opportunity_index,
                    )

                if opportunity_key not in counted_opportunity_keys:
                    counted_opportunity_keys.add(opportunity_key)
                    open_positions += _opportunity_openings(opportunity)

            if program_is_hiring:
                program_ak = program.get("programAk")

                if program_ak not in (None, ""):
                    program_key = ("programAk", str(program_ak))
                else:
                    program_key = (
                        "position",
                        trade_index,
                        program_index,
                    )

                hiring_program_keys.add(program_key)

        if trade_is_hiring:
            trade_name = trade.get("tradeName") or trade.get("displayTradeName")

            if trade_name and trade_name not in seen_hiring_trade_names:
                seen_hiring_trade_names.add(trade_name)
                hiring_trade_names.append(trade_name)

    return {
        "programs_hiring": len(hiring_program_keys),
        "open_positions": open_positions,
        "hiring_trade_names": hiring_trade_names,
    }


TEMPLATE_FILTERS = {
    "format_date": format_date,
    "format_wage": format_wage,
    "percent_of": percent_of,
    "chat_markdown": chat_markdown,
    "typical_program_length": typical_program_length,
    "program_hiring_stats": program_hiring_stats,
}
