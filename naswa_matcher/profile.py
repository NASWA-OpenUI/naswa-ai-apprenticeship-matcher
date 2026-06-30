import json
import re
from urllib.parse import urlencode

from naswa_matcher.location_matching import should_use_location_matching


def strip_profile(text: str) -> str:
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text)
    text = re.sub(r"<thinking>[\s\S]*$", "", text)
    text = re.sub(r"<profile>[\s\S]*?</profile>", "", text)
    text = re.sub(r"<profile>[\s\S]*$", "", text)
    return text.strip()


def extract_profile(text: str) -> dict | None:
    match = re.search(r"<profile>([\s\S]*?)</profile>", text)
    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def profile_rank_params(profile: dict) -> list[tuple[str, str]]:
    params = [("ranked", "true")]

    for like in profile.get("likes", []):
        params.append(("likes", like))

    for dislike in profile.get("dislikes", []):
        params.append(("dislikes", dislike))

    for key in ["location", "transportation"]:
        value = profile.get(key)
        if value:
            params.append((key, value))

    if not should_use_location_matching(profile):
        params.append(("use_location_matching", "false"))

    return params


def profile_rank_url(profile: dict) -> str:
    return "/opportunities?" + urlencode(profile_rank_params(profile))
