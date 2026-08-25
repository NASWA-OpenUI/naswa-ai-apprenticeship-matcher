from urllib.parse import parse_qs, urlparse

import pytest

from naswa_matcher.match_target import MatchTarget
from naswa_matcher.profile import (
    build_profile,
    build_profile_from_input,
    extract_profile,
    has_profile_query_params,
    profile_chat_url,
    profile_match_url,
    profile_query_params,
    profile_rank_params,
    profile_rank_url,
    profile_url,
    strip_profile,
)


def test_strip_profile_removes_complete_profile_tag():
    """Remove a complete hidden profile tag from assistant-visible text."""
    text = 'Sounds good.\n<profile>{"confirmed": false}</profile>'

    assert strip_profile(text) == "Sounds good."


def test_strip_profile_removes_partial_profile_tag():
    """Remove an unfinished profile tag from streaming assistant text."""
    text = 'Sounds good.\n<profile>{"confirmed":'

    assert strip_profile(text) == "Sounds good."


def test_strip_profile_removes_complete_thinking_tag():
    """Remove a complete hidden thinking tag from assistant-visible text."""
    text = "<thinking>Internal notes here.</thinking>\nSounds good."

    assert strip_profile(text) == "Sounds good."


def test_strip_profile_removes_partial_thinking_tag():
    """Remove an unfinished thinking tag from streaming assistant text."""
    text = "<thinking>Internal notes here"

    assert strip_profile(text) == ""


def test_strip_profile_removes_thinking_and_profile_tags():
    """Remove both hidden thinking and profile tags from assistant-visible text."""
    text = (
        "<thinking>Internal notes.</thinking>\n"
        "Sounds good.\n"
        '<profile>{"confirmed": true}</profile>'
    )

    assert strip_profile(text) == "Sounds good."


def test_strip_profile_strips_surrounding_whitespace():
    """Trim surrounding whitespace after hidden tags are removed."""
    text = '\n\n  Sounds good.  \n<profile>{"confirmed": true}</profile>\n'

    assert strip_profile(text) == "Sounds good."


def test_extract_profile_returns_profile_dict_from_valid_tag():
    """Return parsed profile JSON when a valid hidden profile tag is present."""
    text = (
        "Great, I have enough to show matches.\n"
        '<profile>{"likes":["math"],"confirmed":true}</profile>'
    )

    assert extract_profile(text) == {
        "likes": ["math"],
        "confirmed": True,
    }


def test_extract_profile_returns_none_when_profile_tag_is_missing():
    """Return None when no hidden profile tag is present."""
    assert extract_profile("Great, I have enough to show matches.") is None


def test_extract_profile_returns_none_when_profile_json_is_invalid():
    """Return None when the hidden profile tag contains invalid JSON."""
    text = '<profile>{"likes": ["math"], "confirmed": true,}</profile>'

    assert extract_profile(text) is None


def test_profile_rank_params_includes_likes_and_dislikes():
    """Include each like and dislike as repeated query params."""
    profile = {
        "likes": ["math", "fixing things"],
        "dislikes": ["writing"],
    }

    assert profile_rank_params(profile) == [
        ("ranked", "true"),
        ("likes", "math"),
        ("likes", "fixing things"),
        ("dislikes", "writing"),
    ]


def test_profile_rank_params_includes_transportation():
    """Include transportation in ranked opportunity query params."""
    profile = {
        "transportation": "public transit",
    }

    assert profile_rank_params(profile) == [
        ("ranked", "true"),
        ("transportation", "public transit"),
    ]


def test_profile_rank_params_omits_empty_transportation():
    """Omit transportation when no transportation value is present."""
    profile = {
        "transportation": None,
    }

    assert profile_rank_params(profile) == [
        ("ranked", "true"),
    ]


def test_profile_rank_url_returns_encoded_ranked_opportunities_url():
    profile = {
        "likes": ["fixing things"],
        "dislikes": ["writing"],
        "transportation": "public transit",
    }

    assert (
        profile_rank_url(profile)
        == "/opportunities?ranked=true&likes=fixing+things&dislikes=writing&transportation=public+transit"
    )


def test_build_profile_defaults_to_unconfirmed_without_name():
    profile = build_profile(
        likes=["math", "working with tools"],
        dislikes=["desk work"],
        transportation="public transit",
    )

    assert profile == {
        "name": None,
        "likes": ["math", "working with tools"],
        "dislikes": ["desk work"],
        "transportation": "public transit",
        "confirmed": False,
    }


def test_build_profile_can_create_confirmed_chat_profile():
    profile = build_profile(
        name="Taylor",
        likes=["electronics"],
        dislikes=[],
        transportation="car",
        confirmed=True,
    )

    assert profile == {
        "name": "Taylor",
        "likes": ["electronics"],
        "dislikes": [],
        "transportation": "car",
        "confirmed": True,
    }


def test_has_profile_query_params_returns_false_when_all_are_missing():
    assert (
        has_profile_query_params(
            likes=[],
            dislikes=[],
            transportation=None,
        )
        is False
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"likes": ["math"]},
        {"dislikes": ["heights"]},
        {"transportation": "car"},
    ],
)
def test_has_profile_query_params_detects_each_supported_value(overrides):
    values = {
        "likes": [],
        "dislikes": [],
        "transportation": None,
    }
    values.update(overrides)

    assert has_profile_query_params(**values)


def test_profile_query_params_includes_active_profile_fields_without_ranked():
    profile = build_profile(
        likes=["math"],
        dislikes=["desk work"],
        transportation="car",
    )

    assert profile_query_params(profile) == [
        ("likes", "math"),
        ("dislikes", "desk work"),
        ("transportation", "car"),
    ]


def test_profile_rank_params_adds_ranked_true_before_profile_params():
    profile = build_profile(
        likes=["math"],
        dislikes=[],
        transportation=None,
    )

    assert profile_rank_params(profile) == [
        ("ranked", "true"),
        ("likes", "math"),
    ]


def test_profile_rank_url_encodes_ranked_profile_query():
    profile = build_profile(
        likes=["math"],
        dislikes=[],
        transportation="car",
    )

    parsed = urlparse(profile_rank_url(profile))
    query = parse_qs(parsed.query)

    assert parsed.path == "/opportunities"
    assert query["ranked"] == ["true"]
    assert query["likes"] == ["math"]
    assert query["transportation"] == ["car"]


def test_profile_chat_url_for_programs_excludes_ranked_and_transportation():
    profile = build_profile(
        likes=["math"],
        dislikes=[],
        transportation="car",
    )

    parsed = urlparse(
        profile_chat_url(
            profile,
            MatchTarget.PROGRAMS,
        )
    )
    query = parse_qs(parsed.query)

    assert parsed.path == "/chat"
    assert "ranked" not in query
    assert query["match_target"] == ["programs"]
    assert query["likes"] == ["math"]
    assert "transportation" not in query


def test_profile_chat_url_for_opportunities_includes_transportation():
    profile = build_profile(
        likes=["construction"],
        dislikes=[],
        transportation="car",
    )

    parsed = urlparse(
        profile_chat_url(
            profile,
            MatchTarget.OPPORTUNITIES,
        )
    )
    query = parse_qs(parsed.query)

    assert parsed.path == "/chat"
    assert query["match_target"] == ["opportunities"]
    assert query["likes"] == ["construction"]
    assert query["transportation"] == ["car"]


def test_blank_optional_values_are_omitted_from_urls():
    profile = build_profile(
        likes=["math", ""],
        dislikes=[""],
        transportation=None,
    )

    query = parse_qs(urlparse(profile_rank_url(profile)).query)

    assert query == {
        "ranked": ["true"],
        "likes": ["math"],
    }


def test_profile_rank_url_preserves_repeated_likes():
    profile = build_profile(
        likes=["math", "fixing things"],
        dislikes=[],
        transportation=None,
    )

    query = parse_qs(urlparse(profile_rank_url(profile)).query)

    assert query["likes"] == ["math", "fixing things"]


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (MatchTarget.PROGRAMS, "/chat?match_target=programs"),
        (MatchTarget.OPPORTUNITIES, "/chat?match_target=opportunities"),
    ],
)
def test_profile_chat_url_preserves_target_for_empty_profile(target, expected):
    profile = build_profile(
        likes=[],
        dislikes=[],
        transportation=None,
    )

    assert profile_chat_url(profile, target) == expected


def test_has_profile_query_params_detects_explicit_blank_transportation():
    assert has_profile_query_params(
        likes=[],
        dislikes=[],
        transportation="",
    )


def test_profile_match_url_for_programs_uses_interest_params_without_ranked():
    profile = build_profile(
        likes=["math", "fixing things"],
        dislikes=["desk work"],
        transportation="car",
    )

    parsed = urlparse(
        profile_match_url(
            profile,
            MatchTarget.PROGRAMS,
        )
    )
    query = parse_qs(parsed.query)

    assert parsed.path == "/programs"
    assert "ranked" not in query
    assert query["likes"] == ["math", "fixing things"]
    assert query["dislikes"] == ["desk work"]
    assert "transportation" not in query


def test_profile_match_url_for_opportunities_keeps_ranked_mode_and_transportation():
    profile = build_profile(
        likes=["math"],
        dislikes=[],
        transportation="car",
    )

    parsed = urlparse(
        profile_match_url(
            profile,
            MatchTarget.OPPORTUNITIES,
        )
    )
    query = parse_qs(parsed.query)

    assert parsed.path == "/opportunities"
    assert query["ranked"] == ["true"]
    assert query["likes"] == ["math"]
    assert query["transportation"] == ["car"]


def test_profile_url_adds_active_profile_query_params():
    profile = build_profile(
        likes=["math", "fixing things"],
        dislikes=["desk work"],
        transportation="car",
    )

    parsed = urlparse(
        profile_url(
            "/api/rank-opportunities",
            profile,
        )
    )
    query = parse_qs(parsed.query)

    assert parsed.path == "/api/rank-opportunities"
    assert query["likes"] == ["math", "fixing things"]
    assert query["dislikes"] == ["desk work"]
    assert query["transportation"] == ["car"]


def test_profile_url_can_exclude_transportation():
    profile = build_profile(
        likes=["math"],
        dislikes=["desk work"],
        transportation="car",
    )

    parsed = urlparse(
        profile_url(
            "/api/rank-programs",
            profile,
            include_transportation=False,
        )
    )
    query = parse_qs(parsed.query)

    assert query == {
        "likes": ["math"],
        "dislikes": ["desk work"],
    }


def test_profile_url_returns_plain_path_for_empty_profile():
    profile = build_profile(
        likes=[],
        dislikes=[],
        transportation=None,
    )

    assert profile_url("/api/rank-programs", profile) == "/api/rank-programs"


def test_build_profile_from_input_normalizes_values():
    profile = build_profile_from_input(
        name="  Paulo  ",
        likes=["  Building things  ", "", "building things", " Math "],
        dislikes=["  Desk work ", "DESK WORK", "  "],
        transportation="  Can drive  ",
        confirmed=True,
    )

    assert profile == {
        "name": "Paulo",
        "likes": ["Building things", "Math"],
        "dislikes": ["Desk work"],
        "transportation": "Can drive",
        "confirmed": True,
    }


def test_build_profile_from_input_defaults_and_normalizes_blank_values():
    profile = build_profile_from_input(
        name=" ",
        likes=[],
        dislikes=[],
        transportation=None,
    )

    assert profile == {
        "name": None,
        "likes": [],
        "dislikes": [],
        "transportation": None,
        "confirmed": False,
    }
