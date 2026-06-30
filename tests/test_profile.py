# tests/test_profile.py

from naswa_matcher.profile import (
    extract_profile,
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


def test_profile_rank_params_includes_ranked_true_first():
    """Start ranked opportunity params with ranked=true."""
    profile = {}

    assert profile_rank_params(profile)[0] == ("ranked", "true")


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
