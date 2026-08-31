from urllib.parse import urlencode

from naswa_matcher.match_target import MatchTarget
from naswa_matcher.profile import (
    build_profile_from_input,
    profile_query_params,
)


def build_demo_match_url(
    *,
    name: str,
    target: MatchTarget,
    likes: list[str],
    dislikes: list[str],
    transportation: str | None = None,
) -> str:
    """Build a demo results URL from a hard-coded sample profile."""
    profile = build_profile_from_input(
        name=name,
        likes=likes,
        dislikes=dislikes,
        transportation=transportation,
    )

    if target is MatchTarget.PROGRAMS:
        path = "/programs"
    elif target is MatchTarget.OPPORTUNITIES:
        path = "/opportunities"
    else:
        raise ValueError(f"Unsupported match target: {target}")

    params = [
        ("name", name),
        *profile_query_params(
            profile,
            include_transportation=(target is MatchTarget.OPPORTUNITIES),
        ),
        ("demo", "true"),
    ]

    return path + "?" + urlencode(params)


TERRY_MATCH_URL = build_demo_match_url(
    name="Terry",
    target=MatchTarget.PROGRAMS,
    likes=[
        "caring for animals",
        "hands-on repair work",
        "troubleshooting mechanical/electrical equipment",
        "fixing and reselling equipment",
        "self-directed learning",
        "biology",
        "physics",
        "understanding how things work",
    ],
    dislikes=[
        "math-heavy work",
        "working on a computer",
    ],
)


DEMO_PROFILES = [
    {
        "id": "terry",
        "first_name": "Terry",
        "title": "Terry the Turtle Guy",
        "emoji": "🐢",
        "accent": "#1e752e",
        "tint": "#e9f4ec",
        "location_label": "Buffalo, NY",
        "transportation_label": "Can drive",
        "bullets": [
            "Looks after a pet turtle",
            "Tinkers with and fixes with aquarium equipment",
            "Resells electronics on Facebook Marketplace",
            "Self-directed learning",
        ],
        "dislike": "computer work",
        "match_url": TERRY_MATCH_URL,
    },
    {
        "id": "dana",
        "first_name": "Dana",
        "title": "Dana the Dancer",
        "emoji": "🩰",
        "accent": "#8a3ea3",
        "tint": "#f4e9f6",
        "location_label": "Albany, NY",
        "transportation_label": "Uses transit",
        "bullets": [
            "Trained in Russian ballet, performs on stage",
            "Loves working one-on-one with people",
            "Draws and does arts & crafts with others",
        ],
        "dislike": None,
        "match_url": None,
    },
    {
        "id": "mark",
        "first_name": "Mark",
        "title": "Mark the Maker",
        "emoji": "🧩",
        "accent": "#2563a8",
        "tint": "#e7eef7",
        "location_label": "Syracuse, NY",
        "transportation_label": "Can drive",
        "bullets": [
            "Builds detailed model kits",
            "Sketches furniture and room layouts",
            "Helps his uncle fix things around the house",
        ],
        "dislike": "writing essays",
        "match_url": None,
    },
    {
        "id": "fiona",
        "first_name": "Fiona",
        "title": "Fiona the Fixer",
        "emoji": "🚲",
        "accent": "#c2610a",
        "tint": "#fbeede",
        "location_label": "Yonkers, NY",
        "transportation_label": "Uses transit",
        "bullets": [
            "Fixes her own bike",
            "Takes apart broken electronics",
            "Makes costumes and props with friends",
        ],
        "dislike": "memorizing for tests",
        "match_url": None,
    },
]
