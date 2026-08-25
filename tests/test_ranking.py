import pytest

from naswa_matcher.ranking import (
    build_job_summary,
    build_ranked_items,
    build_scoring_prompt,
    normalize_tier,
    parse_scoring_response,
    sort_ranked_items,
)


@pytest.mark.parametrize(
    "tier",
    [
        "Strong",
        "Moderate",
        "Weak",
    ],
)
def test_normalize_tier_returns_valid_tier(tier):
    """Verifies that valid scoring tiers are returned unchanged."""
    assert normalize_tier(tier) == tier


@pytest.mark.parametrize(
    "tier",
    [
        None,
        "",
        "strong",
        "Excellent",
        "Not a tier",
    ],
)
def test_normalize_tier_defaults_unexpected_values_to_weak(tier):
    """Verifies that missing or unexpected model tiers safely fall back to Weak."""
    assert normalize_tier(tier) == "Weak"


def test_build_job_summary_extracts_posting_and_onet_fields():
    """Verifies that build_job_summary extracts the compact opportunity fields
    sent to the scoring model."""
    job = {
        "id": "electrician-apprentice",
        "posting": {
            "jobTitle": "Electrician Apprentice",
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

    summary = build_job_summary(job)

    assert summary == {
        "id": "electrician-apprentice",
        "title": "Electrician Apprentice",
        "requirements_summary": "Must have reliable transportation.",
        "transportation_requirement": "Must have reliable transportation.",
        "description": "Install, maintain, and repair electrical wiring.",
        "skills": [
            "Troubleshooting",
            "Critical Thinking",
        ],
        "activities": [
            "Repair electrical equipment",
        ],
        "work_styles": [
            "Attention to Detail",
        ],
    }


def test_build_job_summary_handles_missing_onet_sections():
    """Verifies that missing optional O*NET sections become empty lists instead
    of raising errors or sending malformed values to the scoring model."""
    job = {
        "id": "partial-job",
        "posting": {
            "jobTitle": "Partial Job",
        },
        "onet": {
            "description": "A partial O*NET record.",
        },
    }

    summary = build_job_summary(job)

    assert summary["description"] == "A partial O*NET record."
    assert summary["skills"] == []
    assert summary["activities"] == []
    assert summary["work_styles"] == []


def test_build_scoring_prompt_includes_profile_and_jobs():
    """Verifies that the scoring prompt includes the active opportunity profile,
    supplied job summaries, and strict JSON response instructions."""
    profile = {
        "likes": ["hands-on work"],
        "dislikes": ["desk work"],
        "transportation": "Can drive",
    }

    prompt = build_scoring_prompt(
        profile,
        [
            {
                "id": "job-1",
                "title": "Electrician Apprentice",
                "transportation_requirement": ("Must have reliable transportation."),
            }
        ],
    )

    assert "Profile:" in prompt
    assert "hands-on work" in prompt
    assert "desk work" in prompt
    assert "Can drive" in prompt
    assert "job-1" in prompt
    assert "Electrician Apprentice" in prompt
    assert "Must have reliable transportation." in prompt
    assert "Return ONLY a JSON array" in prompt


def test_build_scoring_prompt_includes_transportation_guidance():
    """Verifies that transportation remains a scoring factor for opportunities."""
    profile = {
        "likes": ["hands-on work"],
        "dislikes": ["desk work"],
        "transportation": "Takes public transit",
    }

    prompt = build_scoring_prompt(
        profile,
        [
            {
                "id": "job-1",
                "transportation_requirement": ("Must have reliable transportation."),
            }
        ],
    )

    assert "Use transportation only when" in prompt
    assert "A transportation concern can be a caveat" in prompt
    assert "Takes public transit" in prompt
    assert "Must have reliable transportation." in prompt


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


def test_build_ranked_items_attaches_scores_to_jobs():
    """Verifies that model scores and derived opportunity summary facts are
    attached to jobs using each job ID."""
    jobs = [
        {
            "id": "job-1",
            "posting": {
                "jobTitle": "Electrician Apprentice",
                "numberOfOpenings": 3,
                "applicationFee": "25",
                "transportationRequirement": (
                    "Must have a valid driver's license and reliable transportation."
                ),
            },
        }
    ]
    scores = [
        {
            "id": "job-1",
            "tier": "Strong",
            "explanation": "Good fit for hands-on technical work.",
        }
    ]
    job_index = {"job-1": 7}

    ranked = build_ranked_items(
        batch_jobs=jobs,
        scores=scores,
        job_index=job_index,
    )

    assert ranked == [
        {
            "id": "job-1",
            "tier": "Strong",
            "tier_order": 0,
            "sort_index": 7,
            "explanation": "Good fit for hands-on technical work.",
            "posting": jobs[0]["posting"],
            "summary": {
                "number_of_openings": 3,
                "application_fee": 25,
                "license_required": True,
            },
        }
    ]


def test_build_ranked_items_defaults_missing_scores_to_weak():
    """Verifies that jobs missing from the model response are kept as Weak matches."""
    jobs = [
        {
            "id": "job-1",
            "posting": {
                "jobTitle": "Electrician Apprentice",
            },
        }
    ]

    ranked = build_ranked_items(
        batch_jobs=jobs,
        scores=[],
        job_index={"job-1": 0},
    )

    assert ranked[0]["id"] == "job-1"
    assert ranked[0]["tier"] == "Weak"
    assert ranked[0]["tier_order"] == 2
    assert ranked[0]["explanation"] == ""


def test_build_ranked_items_sorts_by_tier_and_original_order():
    """Verifies that ranked batch results are sorted by tier and then by their
    original source order."""
    jobs = [
        {
            "id": "weak-earlier",
            "posting": {
                "jobTitle": "Weak Earlier Job",
            },
        },
        {
            "id": "strong-earlier",
            "posting": {
                "jobTitle": "Strong Earlier Job",
            },
        },
        {
            "id": "strong-later",
            "posting": {
                "jobTitle": "Strong Later Job",
            },
        },
        {
            "id": "moderate",
            "posting": {
                "jobTitle": "Moderate Job",
            },
        },
    ]
    scores = [
        {
            "id": "weak-earlier",
            "tier": "Weak",
            "explanation": "",
        },
        {
            "id": "strong-earlier",
            "tier": "Strong",
            "explanation": "",
        },
        {
            "id": "strong-later",
            "tier": "Strong",
            "explanation": "",
        },
        {
            "id": "moderate",
            "tier": "Moderate",
            "explanation": "",
        },
    ]
    job_index = {
        "weak-earlier": 0,
        "strong-earlier": 1,
        "strong-later": 2,
        "moderate": 3,
    }

    ranked = build_ranked_items(
        batch_jobs=jobs,
        scores=scores,
        job_index=job_index,
    )

    assert [item["id"] for item in ranked] == [
        "strong-earlier",
        "strong-later",
        "moderate",
        "weak-earlier",
    ]


def test_sort_ranked_items_orders_by_tier_and_original_order():
    """Verifies that final ranked results sort by tier and use original source
    order as the tie-breaker."""
    ranked = [
        {
            "id": "weak-earlier",
            "tier_order": 2,
            "sort_index": 0,
        },
        {
            "id": "strong-later",
            "tier_order": 0,
            "sort_index": 3,
        },
        {
            "id": "strong-earlier",
            "tier_order": 0,
            "sort_index": 2,
        },
        {
            "id": "moderate",
            "tier_order": 1,
            "sort_index": 4,
        },
    ]

    sorted_items = sort_ranked_items(ranked)

    assert [item["id"] for item in sorted_items] == [
        "strong-earlier",
        "strong-later",
        "moderate",
        "weak-earlier",
    ]
