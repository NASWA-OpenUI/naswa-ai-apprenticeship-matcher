from starlette.requests import Request

from naswa_matcher.back_link import (
    BackLink,
    back_link_from_referer,
)

FALLBACK = BackLink(
    href="/opportunities",
    label="← All opportunities",
)

ALLOWED_SOURCES = frozenset(
    {
        "opportunities_browse",
        "opportunity_matches",
        "program_detail",
        "saved",
        "data_sources",
    }
)


def make_request(
    *,
    path: str = "/opportunities/example-job",
    referer: str | None = None,
) -> Request:
    headers = [
        (b"host", b"testserver"),
    ]

    if referer is not None:
        headers.append((b"referer", referer.encode()))

    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": path,
            "query_string": b"",
            "headers": headers,
        }
    )


def test_returns_fallback_without_referer():
    request = make_request()

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == FALLBACK


def test_returns_browse_opportunities_link():
    request = make_request(referer="http://testserver/opportunities")

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == BackLink(
        href="/opportunities",
        label="← All opportunities",
        source="opportunities_browse",
        use_history=True,
    )


def test_returns_ranked_opportunities_link():
    request = make_request(
        referer=("http://testserver/opportunities" "?likes=fixing+things" "&likes=math")
    )

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == BackLink(
        href=("/opportunities" "?likes=fixing+things" "&likes=math"),
        label="← Back to your matches",
        source="opportunity_matches",
        use_history=True,
    )


def test_ranked_opportunities_only_requires_likes():
    request = make_request(
        referer=("http://testserver/opportunities" "?likes=woodworking")
    )

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result.source == "opportunity_matches"
    assert result.label == "← Back to your matches"


def test_preserves_full_query_string():
    request = make_request(
        referer=(
            "http://testserver/opportunities"
            "?likes=math"
            "&likes=repairing+things"
            "&dislikes=desk+work"
            "&transportation=car"
        )
    )

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result.href == (
        "/opportunities"
        "?likes=math"
        "&likes=repairing+things"
        "&dislikes=desk+work"
        "&transportation=car"
    )


def test_returns_program_detail_link():
    request = make_request(referer=("http://testserver/programs/47-2111.00"))

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == BackLink(
        href="/programs/47-2111.00",
        label="← Back to program details",
        source="program_detail",
        use_history=True,
    )


def test_returns_saved_link():
    request = make_request(referer="http://testserver/saved")

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == BackLink(
        href="/saved",
        label="← Back to saved opportunities",
        source="saved",
        use_history=True,
    )


def test_returns_data_sources_link():
    request = make_request(referer="http://testserver/data-sources")

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == BackLink(
        href="/data-sources",
        label="← Back to data sources",
        source="data_sources",
        use_history=True,
    )


def test_rejects_external_referer():
    request = make_request(referer="https://example.com/saved")

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == FALLBACK


def test_rejects_external_subdomain():
    request = make_request(referer="https://testserver.example.com/saved")

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == FALLBACK


def test_rejects_unrecognized_route():
    request = make_request(referer="http://testserver/health")

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == FALLBACK


def test_rejects_api_route():
    request = make_request(
        referer=("http://testserver/api/rank-opportunities" "?likes=math")
    )

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == FALLBACK


def test_rejects_recognized_but_disallowed_source():
    request = make_request(referer="http://testserver/chat")

    result = back_link_from_referer(
        request,
        allowed_sources=ALLOWED_SOURCES,
        fallback=FALLBACK,
    )

    assert result == FALLBACK
