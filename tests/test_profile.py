from urllib.parse import parse_qs, urlparse

import pytest

from naswa_matcher.profile import (
    build_profile,
    extract_profile,
    has_profile_query_params,
    profile_chat_url,
    profile_query_params,
    profile_rank_params,
    profile_rank_url,
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


def test_profile_rank_params_includes_location_and_transportation():
    """Include location and transportation params when present."""
    profile = {
        "location": "Buffalo",
        "transportation": "public transit",
    }

    assert profile_rank_params(profile) == [
        ("ranked", "true"),
        ("location", "Buffalo"),
        ("transportation", "public transit"),
    ]


def test_profile_rank_params_omits_empty_location_and_transportation():
    """Omit blank location and transportation params."""
    profile = {
        "location": "",
        "transportation": None,
    }

    assert profile_rank_params(profile) == [("ranked", "true")]


def test_profile_rank_params_includes_location_matching_false():
    """Include use_location_matching=false when the profile disables location matching."""
    profile = {
        "likes": ["math"],
        "use_location_matching": False,
    }

    assert profile_rank_params(profile) == [
        ("ranked", "true"),
        ("likes", "math"),
        ("use_location_matching", "false"),
    ]


def test_profile_rank_params_omits_location_matching_when_true():
    """Omit use_location_matching when location matching is enabled."""
    profile = {
        "likes": ["math"],
        "use_location_matching": True,
    }

    assert profile_rank_params(profile) == [
        ("ranked", "true"),
        ("likes", "math"),
    ]


def test_profile_rank_url_returns_encoded_ranked_opportunities_url():
    """Return a ranked opportunities URL with encoded profile query params."""
    profile = {
        "likes": ["fixing things"],
        "dislikes": ["writing"],
        "location": "Buffalo",
        "transportation": "public transit",
        "use_location_matching": False,
    }

    assert (
        profile_rank_url(profile)
        == "/opportunities?ranked=true&likes=fixing+things&dislikes=writing&location=Buffalo&transportation=public+transit&use_location_matching=false"
    )


def test_build_profile_defaults_to_unconfirmed_without_name():
    profile = build_profile(
        likes=["math", "working with tools"],
        dislikes=["desk work"],
        location="Buffalo",
        transportation="public transit",
        use_location_matching=True,
    )

    assert profile == {
        "name": None,
        "likes": ["math", "working with tools"],
        "dislikes": ["desk work"],
        "location": "Buffalo",
        "transportation": "public transit",
        "use_location_matching": True,
        "confirmed": False,
    }


def test_build_profile_can_create_confirmed_chat_profile():
    profile = build_profile(
        name="Taylor",
        likes=["electronics"],
        dislikes=[],
        location="Albany",
        transportation="car",
        use_location_matching=True,
        confirmed=True,
    )

    assert profile == {
        "name": "Taylor",
        "likes": ["electronics"],
        "dislikes": [],
        "location": "Albany",
        "transportation": "car",
        "use_location_matching": True,
        "confirmed": True,
    }


def test_has_profile_query_params_returns_false_when_all_are_missing():
    assert (
        has_profile_query_params(
            likes=[],
            dislikes=[],
            location=None,
            transportation=None,
            use_location_matching=None,
        )
        is False
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"likes": ["math"]},
        {"dislikes": ["heights"]},
        {"location": "Buffalo"},
        {"transportation": "car"},
        {"use_location_matching": False},
    ],
)
def test_has_profile_query_params_detects_each_supported_value(overrides):
    values = {
        "likes": [],
        "dislikes": [],
        "location": None,
        "transportation": None,
        "use_location_matching": None,
    }
    values.update(overrides)

    assert has_profile_query_params(**values)


def test_profile_query_params_includes_profile_fields_without_ranked():
    profile = build_profile(
        likes=["math"],
        dislikes=["desk work"],
        location="Buffalo",
        transportation="car",
        use_location_matching=True,
    )

    assert profile_query_params(profile) == [
        ("likes", "math"),
        ("dislikes", "desk work"),
        ("location", "Buffalo"),
        ("transportation", "car"),
    ]


def test_profile_rank_params_adds_ranked_true_before_profile_params():
    profile = build_profile(
        likes=["math"],
        dislikes=[],
        location=None,
        transportation=None,
        use_location_matching=True,
    )

    assert profile_rank_params(profile) == [
        ("ranked", "true"),
        ("likes", "math"),
    ]


def test_profile_rank_url_encodes_ranked_profile_query():
    profile = build_profile(
        likes=["math"],
        dislikes=[],
        location="Buffalo",
        transportation=None,
        use_location_matching=True,
    )

    parsed = urlparse(profile_rank_url(profile))
    query = parse_qs(parsed.query)

    assert parsed.path == "/opportunities"
    assert query["ranked"] == ["true"]
    assert query["likes"] == ["math"]
    assert query["location"] == ["Buffalo"]


def test_profile_chat_url_excludes_ranked_parameter():
    profile = build_profile(
        likes=["math"],
        dislikes=[],
        location="Buffalo",
        transportation=None,
        use_location_matching=True,
    )

    parsed = urlparse(profile_chat_url(profile))
    query = parse_qs(parsed.query)

    assert parsed.path == "/chat"
    assert "ranked" not in query
    assert query["likes"] == ["math"]
    assert query["location"] == ["Buffalo"]


def test_false_location_matching_is_included_in_rank_and_chat_urls():
    profile = build_profile(
        likes=["construction"],
        dislikes=[],
        location="Buffalo",
        transportation="car",
        use_location_matching=False,
    )

    rank_query = parse_qs(urlparse(profile_rank_url(profile)).query)
    chat_query = parse_qs(urlparse(profile_chat_url(profile)).query)

    assert rank_query["use_location_matching"] == ["false"]
    assert chat_query["use_location_matching"] == ["false"]


def test_blank_optional_values_are_omitted_from_urls():
    profile = build_profile(
        likes=["math", ""],
        dislikes=[""],
        location="",
        transportation=None,
        use_location_matching=True,
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
        location=None,
        transportation=None,
        use_location_matching=True,
    )

    query = parse_qs(urlparse(profile_rank_url(profile)).query)

    assert query["likes"] == ["math", "fixing things"]


def test_profile_chat_url_returns_plain_chat_path_for_empty_profile():
    profile = build_profile(
        likes=[],
        dislikes=[],
        location=None,
        transportation=None,
        use_location_matching=True,
    )

    assert profile_chat_url(profile) == "/chat"


def test_has_profile_query_params_detects_explicit_blank_string():
    assert has_profile_query_params(
        likes=[],
        dislikes=[],
        location="",
        transportation=None,
        use_location_matching=None,
    )
