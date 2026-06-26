import pytest

from naswa_matcher.ranking import (
    build_job_summary,
    build_scoring_prompt,
    parse_scoring_response,
)


def test_build_job_summary_extracts_onet_fields():
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


def test_parse_scoring_response_accepts_plain_json():
    raw = '[{"id":"job-1","tier":"Strong","explanation":"Good match."}]'

    assert parse_scoring_response(raw) == [
        {
            "id": "job-1",
            "tier": "Strong",
            "explanation": "Good match.",
        }
    ]


def test_parse_scoring_response_accepts_fenced_json():
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
    with pytest.raises(ValueError):
        parse_scoring_response('{"id":"job-1","tier":"Strong"}')
