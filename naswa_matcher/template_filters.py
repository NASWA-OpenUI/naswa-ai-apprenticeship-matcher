from collections import Counter

from markdown_it import MarkdownIt
from markupsafe import Markup

_MARKDOWN = MarkdownIt("js-default").disable("image")


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


TEMPLATE_FILTERS = {
    "format_date": format_date,
    "format_wage": format_wage,
    "percent_of": percent_of,
    "chat_markdown": chat_markdown,
    "typical_program_length": typical_program_length,
}
