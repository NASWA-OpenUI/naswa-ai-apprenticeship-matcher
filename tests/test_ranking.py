import pytest

from naswa_matcher.ranking import (
    build_job_summary,
    build_scoring_prompt,
    parse_scoring_response,
)


def make_rankable_job(
    *,
    location_summary: str = "Binghamton, NY area",
    regions: list[str] | None = None,
) -> dict:
    """Builds a compact O*NET-backed job fixture for testing ranking prompt
    and summary behavior without depending on the full route fixtures."""
    return {
        "id": "electrician-apprentice-fixture",
        "posting": {
            "jobTitle": "Electrician Apprentice",
            "locationSummary": location_summary,
            "regions": regions or ["Southern Tier"],
            "requirementsSummary": "Applicants should like hands-on technical work.",
            "transportationRequirement": "Must have reliable transportation.",
            "allRequirements": [
                "Must have reliable transportation.",
                "Jurisdiction includes Broome County.",
            ],
        },
        "onet": {
            "description": "Install, maintain, and repair electrical wiring and equipment.",
            "skills": {
                "data": {
                    "element": [
                        {"name": "Troubleshooting"},
                        {"name": "Repairing"},
                    ]
                }
            },
            "detailed_work_activities": {
                "data": {
                    "activity": [
                        {"title": "Repair electrical equipment."},
                        {"title": "Install electrical components."},
                    ]
                }
            },
            "work_styles": {
                "data": {
                    "element": [
                        {"name": "Attention to Detail"},
                        {"name": "Dependability"},
                    ]
                }
            },
        },
    }


def test_build_job_summary_extracts_onet_fields():
    """Verifies that build_job_summary extracts the core posting fields,
    location fit, and compact O*NET fields sent to the scoring model."""
    profile = {"location": "Buffalo area"}

    job = {
        "id": "electrician-apprentice",
        "posting": {
            "jobTitle": "Electrician Apprentice",
            "locationSummary": "Buffalo, NY area",
            "regions": ["Western New York"],
            "requirementsSummary": "Must have reliable transportation.",
            "transportationRequirement": "Must have reliable transportation.",
        },
        "onet": {
            "description": "Install, maintain, and repair electrical wiring.",
            "skills": {
                "data": {
                    "element": [
                        {"name": "Troubleshooting"},
                        {"name": "Critical Thinking"},
                    ]
                }
            },
            "detailed_work_activities": {
                "data": {
                    "activity": [
                        {"title": "Repair electrical equipment"},
                    ]
                }
            },
            "work_styles": {
                "data": {
                    "element": [
                        {"name": "Attention to Detail"},
                    ]
                }
            },
        },
    }

    summary = build_job_summary(profile, job)

    assert summary["id"] == "electrician-apprentice"
    assert summary["title"] == "Electrician Apprentice"
    assert summary["location_fit"] == "local"
    assert summary["skills"] == ["Troubleshooting", "Critical Thinking"]
    assert summary["activities"] == ["Repair electrical equipment"]
    assert summary["work_styles"] == ["Attention to Detail"]


def test_build_job_summary_handles_missing_onet_sections():
    """Verifies that missing optional O*NET sections become empty lists instead
    of raising errors or sending malformed values to the scoring model."""
    profile = {"location": "Buffalo area"}

    job = {
        "id": "partial-job",
        "posting": {
            "jobTitle": "Partial Job",
            "locationSummary": "Buffalo, NY area",
        },
        "onet": {
            "description": "A partial O*NET record.",
        },
    }

    summary = build_job_summary(profile, job)

    assert summary["skills"] == []
    assert summary["activities"] == []
    assert summary["work_styles"] == []


def test_build_scoring_prompt_includes_profile_and_jobs():
    """Verifies that the scoring prompt includes the user profile, supplied job
    summaries, and strict JSON response instructions."""
    profile = {
        "likes": ["hands-on work"],
        "dislikes": [],
        "location": "Buffalo area",
        "transportation": "car",
    }

    prompt = build_scoring_prompt(
        profile,
        [
            {
                "id": "job-1",
                "title": "Electrician Apprentice",
                "location_fit": "local",
            }
        ],
    )

    assert "User profile:" in prompt
    assert "hands-on work" in prompt
    assert "job-1" in prompt
    assert "Return ONLY a JSON array" in prompt


def test_build_scoring_prompt_includes_location_guidance_when_matching_enabled():
    """Verifies that location-specific ranking instructions are included when
    the user's profile should use location matching."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": True,
    }

    prompt = build_scoring_prompt(profile, [{"id": "job-1", "location_fit": "far"}])

    assert "Location is a major ranking factor" in prompt
    assert "If location_fit is far" in prompt
    assert "Do not use location or transportation as ranking factors" not in prompt


def test_build_scoring_prompt_removes_location_guidance_when_matching_disabled():
    """Verifies that location and transportation guidance is removed when the
    user is open to statewide opportunities."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": False,
    }

    prompt = build_scoring_prompt(profile, [{"id": "job-1"}])

    assert "Do not use location or transportation as ranking factors" in prompt
    assert "Do not mention the user's statewide flexibility in every explanation" in prompt

    assert "Location is a major ranking factor" not in prompt
    assert "If location_fit is far" not in prompt
    assert "Having a car helps with local travel" not in prompt


def test_parse_scoring_response_accepts_plain_json():
    """Verifies that a valid plain JSON array from the model parses into the
    expected list of ranking objects."""
    raw = '[{"id":"job-1","tier":"Strong","explanation":"Good match."}]'

    assert parse_scoring_response(raw) == [
        {
            "id": "job-1",
            "tier": "Strong",
            "explanation": "Good match.",
        }
    ]


def test_parse_scoring_response_accepts_fenced_json():
    """Verifies that parse_scoring_response tolerates markdown-fenced JSON,
    which LLMs may return despite the prompt instructions."""
    raw = """```json
[{"id":"job-1","tier":"Moderate","explanation":"Some fit."}]
```"""

    assert parse_scoring_response(raw) == [
        {
            "id": "job-1",
            "tier": "Moderate",
            "explanation": "Some fit.",
        }
    ]


def test_parse_scoring_response_rejects_non_array_json():
    """Verifies that object-shaped JSON is rejected because the scoring
    contract requires a JSON array with one object per job."""
    with pytest.raises(ValueError):
        parse_scoring_response('{"id":"job-1","tier":"Strong"}')


def test_build_job_summary_includes_location_fit_when_location_matching_enabled():
    """Verifies that build_job_summary includes derived location fit and
    transportation fields when location matching is enabled."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": True,
    }

    summary = build_job_summary(profile, make_rankable_job())

    assert summary["location_fit"] == "nearby"
    assert summary["transportation_requirement"] == "Must have reliable transportation."
    assert summary["location"] == "Binghamton, NY area"
    assert summary["regions"] == ["Southern Tier"]


def test_build_job_summary_omits_location_fit_when_location_matching_disabled():
    """Verifies that build_job_summary removes derived location and
    transportation signals when statewide matching disables location logic."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": False,
    }

    summary = build_job_summary(profile, make_rankable_job())

    assert "location_fit" not in summary
    assert "transportation_requirement" not in summary

    # Keep real job location context available, but not the derived ranking signal.
    assert summary["location"] == "Binghamton, NY area"
    assert summary["regions"] == ["Southern Tier"]
