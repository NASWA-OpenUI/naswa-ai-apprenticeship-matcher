import json
import re
from urllib.parse import urlencode

from naswa_matcher.location_matching import should_use_location_matching


def strip_profile(text: str) -> str:
    """Remove hidden reasoning and profile tags from an assistant response."""
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text)
    text = re.sub(r"<thinking>[\s\S]*$", "", text)
    text = re.sub(r"<profile>[\s\S]*?</profile>", "", text)
    text = re.sub(r"<profile>[\s\S]*$", "", text)
    return text.strip()


def extract_profile(text: str) -> dict | None:
    """Extract a JSON profile from an assistant response."""
    match = re.search(r"<profile>([\s\S]*?)</profile>", text)
    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def build_profile(
    *,
    likes: list[str],
    dislikes: list[str],
    location: str | None,
    transportation: str | None,
    use_location_matching: bool,
    name: str | None = None,
    confirmed: bool = False,
) -> dict:
    """Build the shared profile shape used by chat and ranking routes."""
    return {
        "name": name,
        "likes": likes,
        "dislikes": dislikes,
        "location": location,
        "transportation": transportation,
        "use_location_matching": use_location_matching,
        "confirmed": confirmed,
    }


def clean_profile_values(values: list[str]) -> list[str]:
    """Return trimmed, non-empty, case-insensitively unique profile values."""
    cleaned: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = str(value).strip()
        key = text.casefold()

        if not text or key in seen:
            continue

        seen.add(key)
        cleaned.append(text)

    return cleaned


def has_profile_query_params(
    *,
    likes: list[str],
    dislikes: list[str],
    location: str | None,
    transportation: str | None,
    use_location_matching: bool | None,
) -> bool:
    """Return whether a request includes any profile-prefill parameters."""
    return any(
        [
            likes,
            dislikes,
            location is not None,
            transportation is not None,
            use_location_matching is not None,
        ]
    )


def profile_query_params(profile: dict) -> list[tuple[str, str]]:
    """Return reusable URL query parameters for a profile."""
    params: list[tuple[str, str]] = []

    for like in profile.get("likes", []):
        if like:
            params.append(("likes", str(like)))

    for dislike in profile.get("dislikes", []):
        if dislike:
            params.append(("dislikes", str(dislike)))

    for key in ["location", "transportation"]:
        value = profile.get(key)
        if value:
            params.append((key, str(value)))

    if not should_use_location_matching(profile):
        params.append(("use_location_matching", "false"))

    return params


def profile_rank_params(profile: dict) -> list[tuple[str, str]]:
    """Return query parameters for the ranked opportunities page."""
    return [
        ("ranked", "true"),
        *profile_query_params(profile),
    ]


def profile_rank_url(profile: dict) -> str:
    """Return the ranked opportunities URL for a profile."""
    return "/opportunities?" + urlencode(profile_rank_params(profile))


def profile_chat_url(profile: dict) -> str:
    """Return a chat URL that preloads a profile."""
    params = profile_query_params(profile)

    if not params:
        return "/chat"

    return "/chat?" + urlencode(params)
