import json
import re
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from naswa_matcher.match_target import MatchTarget


class ChatProfileUpdate(BaseModel):
    """Profile values submitted from the profile-edit modal."""

    name: str | None = None
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    transportation: str | None = None


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
    transportation: str | None = None,
    name: str | None = None,
    confirmed: bool = False,
) -> dict:
    """Build the shared profile shape used by chat and ranking routes."""
    return {
        "name": name,
        "likes": likes,
        "dislikes": dislikes,
        "transportation": transportation,
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


def build_profile_from_input(
    *,
    likes: list[str],
    dislikes: list[str],
    transportation: str | None = None,
    name: str | None = None,
    confirmed: bool = False,
) -> dict:
    """Build a normalized profile from request or form input."""
    return build_profile(
        name=(name or "").strip() or None,
        likes=clean_profile_values(likes),
        dislikes=clean_profile_values(dislikes),
        transportation=(transportation or "").strip() or None,
        confirmed=confirmed,
    )


def has_profile_query_params(
    *,
    likes: list[str],
    dislikes: list[str],
    transportation: str | None = None,
) -> bool:
    """Return whether a request includes any profile-prefill parameters."""
    return any(
        [
            likes,
            dislikes,
            transportation is not None,
        ]
    )


def profile_query_params(
    profile: dict,
    *,
    include_transportation: bool = True,
) -> list[tuple[str, str]]:
    """Return reusable URL query parameters for the active profile fields."""
    params: list[tuple[str, str]] = []

    for like in profile.get("likes", []):
        if like:
            params.append(("likes", str(like)))

    for dislike in profile.get("dislikes", []):
        if dislike:
            params.append(("dislikes", str(dislike)))

    transportation = profile.get("transportation")
    if include_transportation and transportation:
        params.append(("transportation", str(transportation)))

    return params


def profile_url(
    path: str,
    profile: dict,
    *,
    include_transportation: bool = True,
) -> str:
    """Return a URL with the profile encoded as query parameters."""
    params = profile_query_params(
        profile,
        include_transportation=include_transportation,
    )

    if not params:
        return path

    return path + "?" + urlencode(params)


def profile_rank_params(profile: dict) -> list[tuple[str, str]]:
    """Return query parameters for the ranked opportunities page."""
    return [
        ("ranked", "true"),
        *profile_query_params(profile),
    ]


def profile_rank_url(profile: dict) -> str:
    """Return the ranked opportunities URL for a profile."""
    return "/opportunities?" + urlencode(profile_rank_params(profile))


def profile_match_url(profile: dict, target: MatchTarget) -> str:
    """Return the matches URL for a profile and matching target."""
    if target is MatchTarget.OPPORTUNITIES:
        return profile_rank_url(profile)

    if target is MatchTarget.PROGRAMS:
        return profile_url(
            "/programs",
            profile,
            include_transportation=False,
        )

    raise ValueError(f"Unsupported match target: {target}")


def profile_chat_url(
    profile: dict,
    target: MatchTarget,
) -> str:
    """Return a chat URL that preloads a profile and preserves its match target."""
    params = [
        ("match_target", target.value),
        *profile_query_params(
            profile,
            include_transportation=(target is MatchTarget.OPPORTUNITIES),
        ),
    ]

    return "/chat?" + urlencode(params)
