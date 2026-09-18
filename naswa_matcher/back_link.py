from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request


@dataclass(frozen=True, slots=True)
class BackLink:
    href: str
    label: str
    source: str | None = None
    use_history: bool = False


@dataclass(frozen=True, slots=True)
class BackLinkRule:
    allowed_sources: frozenset[str]
    fallback: BackLink


BACK_LINK_RULES = {
    "opportunity_detail": BackLinkRule(
        allowed_sources=frozenset(
            {
                "opportunities_browse",
                "opportunity_matches",
                "program_detail",
                "saved",
                "data_sources",
            }
        ),
        fallback=BackLink(
            href="/opportunities",
            label="← All opportunities",
        ),
    ),
    "program_detail": BackLinkRule(
        allowed_sources=frozenset(
            {
                "programs_browse",
                "program_matches",
                "data_sources",
            }
        ),
        fallback=BackLink(
            href="/programs",
            label="← All apprenticeship programs",
        ),
    ),
    "saved_opportunities": BackLinkRule(
        allowed_sources=frozenset(
            {
                "home",
                "chat",
                "demo",
                "ai_disclosure",
                "data_sources",
                "opportunities_browse",
                "opportunity_matches",
                "opportunity_detail",
                "programs_browse",
                "program_matches",
                "program_detail",
            }
        ),
        fallback=BackLink(
            href="/",
            label="← Back to home",
        ),
    ),
}


def _has_profile_query(
    query_string: str,
) -> bool:
    params = parse_qs(
        query_string,
        keep_blank_values=True,
    )

    return "likes" in params


def _is_detail_path(
    path: str,
    prefix: str,
) -> bool:
    if not path.startswith(prefix):
        return False

    remainder = path.removeprefix(prefix)

    return bool(remainder) and "/" not in remainder


def _classify_source(
    path: str,
    query_string: str,
) -> tuple[str, str] | None:
    """Return the source key and Back label for recognized pages."""
    if path == "/":
        return "home", "← Back to home"

    if path == "/chat":
        return "chat", "← Back to conversation"

    if path == "/demo":
        return "demo", "← Back to demo profiles"

    if path == "/ai-disclosure":
        return "ai_disclosure", "← Back to AI disclosure"

    if path == "/data-sources":
        return "data_sources", "← Back to data sources"

    if path == "/saved":
        return (
            "saved",
            "← Back to saved opportunities",
        )

    if path == "/opportunities":
        if _has_profile_query(query_string):
            return (
                "opportunity_matches",
                "← Back to your matches",
            )

        return (
            "opportunities_browse",
            "← All opportunities",
        )

    if _is_detail_path(
        path,
        "/opportunities/",
    ):
        return (
            "opportunity_detail",
            "← Back to opportunity details",
        )

    if path == "/programs":
        if _has_profile_query(query_string):
            return (
                "program_matches",
                "← Back to your matches",
            )

        return (
            "programs_browse",
            "← All apprenticeship programs",
        )

    if _is_detail_path(
        path,
        "/programs/",
    ):
        return (
            "program_detail",
            "← Back to program details",
        )

    return None


def back_link_from_referer(
    request: Request,
    *,
    allowed_sources: set[str] | frozenset[str],
    fallback: BackLink,
) -> BackLink:
    """Return a Back link for a recognized same-site Referer."""
    referer = request.headers.get("referer")

    if not referer:
        return fallback

    try:
        parsed = urlsplit(referer)
    except ValueError:
        return fallback

    if parsed.hostname != request.url.hostname:
        return fallback

    classified = _classify_source(
        parsed.path,
        parsed.query,
    )

    if classified is None:
        return fallback

    source, label = classified

    if source not in allowed_sources:
        return fallback

    href = parsed.path

    if parsed.query:
        href += f"?{parsed.query}"

    return BackLink(
        href=href,
        label=label,
        source=source,
        use_history=True,
    )


def back_link_for_request(
    request: Request,
) -> BackLink:
    """Return the configured Back link for the current route."""
    route = request.scope.get("route")
    route_name = getattr(route, "name", None)

    rule = BACK_LINK_RULES.get(route_name)

    if rule is None:
        raise ValueError(f"No Back link rule configured for route: {route_name}")

    return back_link_from_referer(
        request,
        allowed_sources=rule.allowed_sources,
        fallback=rule.fallback,
    )
