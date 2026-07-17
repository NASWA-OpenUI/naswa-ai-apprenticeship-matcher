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


TEMPLATE_FILTERS = {
    "format_date": format_date,
    "format_wage": format_wage,
    "percent_of": percent_of,
    "chat_markdown": chat_markdown,
}
