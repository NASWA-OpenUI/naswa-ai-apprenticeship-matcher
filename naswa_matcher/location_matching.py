from __future__ import annotations

import re

LOCATION_GROUP_TERMS = {
    "western": [
        "western",
        "western new york",
        "southwestern ny",
        "southwestern new york",
        "buffalo",
        "niagara",
        "niagara falls",
        "orchard park",
        "west seneca",
        "olean",
        "erie",
        "cattaraugus",
        "chautauqua",
        "allegany",
        "genesee",
        "orleans",
        "wyoming",
    ],
    "finger_lakes": [
        "finger lakes",
        "rochester",
        "geneva",
        "monroe",
        "ontario",
        "wayne",
        "seneca",
        "yates",
        "livingston",
    ],
    "southern_tier": [
        "southern tier",
        "binghamton",
        "elmira",
        "ithaca",
        "olean",
        "whitney point",
        "horseheads",
        "broome",
        "chemung",
        "chenango",
        "delaware",
        "schuyler",
        "steuben",
        "tioga",
        "tompkins",
    ],
    "central": [
        "central",
        "central new york",
        "syracuse",
        "east syracuse",
        "clay",
        "liverpool",
        "oswego",
        "cayuga",
        "cortland",
        "madison",
        "onondaga",
    ],
    "mohawk_valley": [
        "mohawk valley",
        "utica",
        "rome",
        "herkimer",
        "oneida",
        "montgomery",
    ],
    "capital": [
        "capital district",
        "capital region",
        "albany",
        "latham",
        "queensbury",
        "troy",
        "schenectady",
        "rensselaer",
        "saratoga",
        "schoharie",
        "warren",
        "washington",
    ],
    "north_country": [
        "north country",
        "watertown",
        "plattsburgh",
        "gouverneur",
        "st. lawrence",
        "st lawrence",
        "clinton",
        "essex",
        "franklin",
        "hamilton",
        "jefferson",
        "lewis",
    ],
    "hudson_valley": [
        "hudson valley",
        "white plains",
        "newburgh",
        "wallkill",
        "highland",
        "pearl river",
        "briarcliff manor",
        "rock tavern",
        "dutchess",
        "orange",
        "putnam",
        "rockland",
        "sullivan",
        "ulster",
        "westchester",
    ],
    "nyc_long_island": [
        "new york city",
        "nyc",
        "five boroughs",
        "manhattan",
        "brooklyn",
        "queens",
        "bronx",
        "staten island",
        "long island",
        "long island city",
        "college point",
        "melville",
        "hauppauge",
        "nassau",
        "suffolk",
        "kings",
        "richmond",
    ],
}


NEARBY_LOCATION_GROUPS = {
    "western": {"finger_lakes", "southern_tier"},
    "finger_lakes": {"western", "southern_tier", "central"},
    "southern_tier": {"western", "finger_lakes", "central", "mohawk_valley"},
    "central": {"finger_lakes", "southern_tier", "mohawk_valley", "north_country"},
    "mohawk_valley": {"central", "southern_tier", "capital", "north_country"},
    "capital": {"mohawk_valley", "north_country", "hudson_valley"},
    "north_country": {"capital", "mohawk_valley", "central"},
    "hudson_valley": {"capital", "nyc_long_island"},
    "nyc_long_island": {"hudson_valley"},
}


LOCATION_FIT_ORDER = {
    "local": 0,
    "nearby": 1,
    "unknown": 2,
    "far": 3,
}


VALID_TIERS = {"Strong", "Moderate", "Weak"}


def text_mentions_term(text: str, term: str) -> bool:
    """Return True if text contains term as a rough phrase match."""
    pattern = r"\b" + re.escape(term.lower()) + r"\b"
    return re.search(pattern, text) is not None


def infer_location_groups(text: str | None) -> set[str]:
    """Infer rough NY location groups from user text or posting text."""
    if not text:
        return set()

    normalized = text.lower()
    groups = set()

    for group, terms in LOCATION_GROUP_TERMS.items():
        if any(text_mentions_term(normalized, term) for term in terms):
            groups.add(group)

    return groups


def job_location_text(job: dict) -> str:
    """Build one searchable location string from the posting's real location fields."""
    posting = job.get("posting", {})

    location_summary = posting.get("locationSummary") or ""

    regions = posting.get("regions") or []
    if isinstance(regions, list):
        regions_text = " ".join(str(region) for region in regions)
    else:
        regions_text = str(regions)

    all_requirements = posting.get("allRequirements") or []
    if isinstance(all_requirements, list):
        requirements_text = " ".join(
            str(requirement) for requirement in all_requirements
        )
    else:
        requirements_text = str(all_requirements)

    return " ".join(
        [
            location_summary,
            regions_text,
            requirements_text,
        ]
    )


def location_fit(profile: dict, job: dict) -> str:
    """
    Return a rough location fit:
    - local: job appears to include the user's region
    - nearby: job appears to include a neighboring region
    - far: known user/job regions do not overlap
    - unknown: not enough info
    """
    user_groups = infer_location_groups(profile.get("location"))
    job_groups = infer_location_groups(job_location_text(job))

    if not user_groups or not job_groups:
        return "unknown"

    if user_groups & job_groups:
        return "local"

    nearby_groups = set()
    for group in user_groups:
        nearby_groups.update(NEARBY_LOCATION_GROUPS.get(group, set()))

    if nearby_groups & job_groups:
        return "nearby"

    return "far"


def cap_tier_by_location(tier: str | None, location_fit: str) -> str:
    """Prevent far-away jobs from being ranked as Strong."""
    if tier not in VALID_TIERS:
        tier = "Weak"

    if location_fit in {"nearby", "far"} and tier == "Strong":
        return "Moderate"

    return tier
