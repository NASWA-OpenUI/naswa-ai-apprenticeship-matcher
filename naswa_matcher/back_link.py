from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request

from naswa_matcher.profile import has_profile_query_params


@dataclass(frozen=True, slots=True)
class BackLink:
    href: str
    label: str
    source: str | None = None
    use_history: bool = False


def _has_profile_query(
    query_string: str,
    *,
    include_transportation: bool,
) -> bool:
    params = parse_qs(
        query_string,
        keep_blank_values=True,
    )

    transportation_values = params.get("transportation")

    transportation = (
        transportation_values[-1]
        if include_transportation and transportation_values is not None
        else None
    )

    return has_profile_query_params(
        likes=params.get("likes", []),
        dislikes=params.get("dislikes", []),
        transportation=transportation,
    )


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
    """
    Return the source key and human-readable Back label for
    recognized page routes.
    """
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
        if _has_profile_query(
            query_string,
            include_transportation=True,
        ):
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
        if _has_profile_query(
            query_string,
            include_transportation=False,
        ):
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
    """
    Return an app-approved Back link derived from the request Referer.

    The Referer must:
    - be HTTP(S)
    - use the same hostname
    - match a recognized page type
    - be allowed by the destination page
    """
    referer = request.headers.get("referer")

    if not referer:
        return fallback

    try:
        parsed = urlsplit(referer)
    except ValueError:
        return fallback

    if parsed.scheme not in {"http", "https"}:
        return fallback

    request_hostname = request.url.hostname
    referer_hostname = parsed.hostname

    if (
        not request_hostname
        or not referer_hostname
        or request_hostname.casefold() != referer_hostname.casefold()
    ):
        return fallback

    # Don't create a Back link pointing at the page we're already on.
    if parsed.path == request.url.path:
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

    # Always turn the Referer back into a relative URL.
    # Even after validation, we never emit an arbitrary absolute URL.
    href = parsed.path or "/"

    if parsed.query:
        href += f"?{parsed.query}"

    return BackLink(
        href=href,
        label=label,
        source=source,
        use_history=True,
    )
