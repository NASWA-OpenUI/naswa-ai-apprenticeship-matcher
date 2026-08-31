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

DANA_MATCH_URL = build_demo_match_url(
    name="Dana",
    target=MatchTarget.PROGRAMS,
    likes=[
        "Russian ballet",
        "performing on stage",
        "working one-on-one with people",
        "physical discipline",
        "drawing",
        "doing arts and crafts with others",
        "creative activities",
    ],
    dislikes=[],
)

MARK_MATCH_URL = build_demo_match_url(
    name="Mark",
    target=MatchTarget.OPPORTUNITIES,
    likes=[
        "building model planes",
        "puzzles",
        "home improvement and repair projects",
        "basketball",
        "shop class",
        "woodworking",
        "math comes easily",
    ],
    dislikes=["electrical wiring", "noisy industrial environments", "sparks and smoke"],
)

FIONA_MATCH_URL = build_demo_match_url(
    name="Fiona",
    target=MatchTarget.OPPORTUNITIES,
    likes=[
        "bike riding",
        "installing/upgrading bike parts",
        "making costumes for drama class",
        "works part-time at a garage" "hands on work",
        "figuring out why something isn't working",
        "weight training",
    ],
    dislikes=["essay writing", "wood gives her splinters", "electronics and computers"],
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
            "creative activities",
        ],
        "dislike": None,
        "match_url": DANA_MATCH_URL,
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
            "Likes jigsaw puzzles, builds model planes",
            "Helps his dad fix things around the house",
            "Enjoys shop class and math",
        ],
        "dislike": "noisy environments",
        "match_url": MARK_MATCH_URL,
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
            "Loves bike riding, knows how to fix her bike",
            "Makes costumes and props for drama class",
            "Worked part-time at uncle’s garage",
        ],
        "dislike": "essay writing",
        "match_url": FIONA_MATCH_URL,
    },
]
