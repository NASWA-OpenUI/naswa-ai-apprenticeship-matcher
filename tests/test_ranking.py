import pytest

from naswa_matcher.ranking import (
    build_job_summary,
    build_ranked_items,
    build_scoring_prompt,
    normalize_tier,
    parse_scoring_response,
    sort_ranked_items,
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

    assert "Profile:" in prompt
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
    assert "Do not mention statewide flexibility in every explanation" in prompt

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


def test_build_ranked_items_attaches_scores_to_jobs():
    """Verifies that model scores and derived opportunity summary facts are
    attached to jobs using each job ID."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": True,
    }
    jobs = [
        {
            "id": "job-1",
            "posting": {
                "jobTitle": "Electrician Apprentice",
                "locationSummary": "Buffalo, NY area",
                "regions": ["Western New York"],
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
        profile=profile,
    )

    assert ranked == [
        {
            "id": "job-1",
            "tier": "Strong",
            "tier_order": 0,
            "sort_index": 7,
            "location_fit": "local",
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
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": True,
    }
    jobs = [
        {
            "id": "job-1",
            "posting": {
                "jobTitle": "Electrician Apprentice",
                "locationSummary": "Buffalo, NY area",
                "regions": ["Western New York"],
            },
        }
    ]

    ranked = build_ranked_items(
        batch_jobs=jobs,
        scores=[],
        job_index={"job-1": 0},
        profile=profile,
    )

    assert ranked[0]["id"] == "job-1"
    assert ranked[0]["tier"] == "Weak"
    assert ranked[0]["tier_order"] == 2
    assert ranked[0]["explanation"] == ""


def test_build_ranked_items_caps_strong_tier_for_far_location():
    """Verifies that location matching prevents far-away jobs from staying Strong."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": True,
    }
    jobs = [
        {
            "id": "nyc-job",
            "posting": {
                "jobTitle": "Electrician Apprentice",
                "locationSummary": "New York City, NY area",
                "regions": ["New York City"],
                "allRequirements": [],
            },
        }
    ]
    scores = [
        {
            "id": "nyc-job",
            "tier": "Strong",
            "explanation": "Good technical match.",
        }
    ]

    ranked = build_ranked_items(
        batch_jobs=jobs,
        scores=scores,
        job_index={"nyc-job": 0},
        profile=profile,
    )

    assert ranked[0]["location_fit"] == "far"
    assert ranked[0]["tier"] == "Moderate"
    assert ranked[0]["tier_order"] == 1


def test_build_ranked_items_does_not_cap_by_location_when_matching_disabled():
    """Verifies that statewide users are not capped by derived location fit."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": False,
    }
    jobs = [
        {
            "id": "nyc-job",
            "posting": {
                "jobTitle": "Electrician Apprentice",
                "locationSummary": "New York City, NY area",
                "regions": ["New York City"],
                "allRequirements": [],
            },
        }
    ]
    scores = [
        {
            "id": "nyc-job",
            "tier": "Strong",
            "explanation": "Good technical match.",
        }
    ]

    ranked = build_ranked_items(
        batch_jobs=jobs,
        scores=scores,
        job_index={"nyc-job": 0},
        profile=profile,
    )

    assert ranked[0]["location_fit"] is None
    assert ranked[0]["tier"] == "Strong"
    assert ranked[0]["tier_order"] == 0


def test_build_ranked_items_sorts_batch_by_tier_location_and_original_order():
    """Verifies that ranked batch results are sorted by tier, location fit, and source order."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": True,
    }
    jobs = [
        {
            "id": "weak-local",
            "posting": {
                "jobTitle": "Weak Local Job",
                "locationSummary": "Buffalo, NY area",
                "regions": ["Western New York"],
                "allRequirements": [],
            },
        },
        {
            "id": "strong-far",
            "posting": {
                "jobTitle": "Strong Far Job",
                "locationSummary": "New York City, NY area",
                "regions": ["New York City"],
                "allRequirements": [],
            },
        },
        {
            "id": "strong-local",
            "posting": {
                "jobTitle": "Strong Local Job",
                "locationSummary": "Buffalo, NY area",
                "regions": ["Western New York"],
                "allRequirements": [],
            },
        },
    ]
    scores = [
        {"id": "weak-local", "tier": "Weak", "explanation": ""},
        {"id": "strong-far", "tier": "Strong", "explanation": ""},
        {"id": "strong-local", "tier": "Strong", "explanation": ""},
    ]
    job_index = {
        "weak-local": 0,
        "strong-far": 1,
        "strong-local": 2,
    }

    ranked = build_ranked_items(
        batch_jobs=jobs,
        scores=scores,
        job_index=job_index,
        profile=profile,
    )

    assert [item["id"] for item in ranked] == [
        "strong-local",
        "strong-far",
        "weak-local",
    ]


def test_sort_ranked_items_orders_by_tier_location_and_original_order():
    """Verifies that final ranked results use tier, location fit, and source order."""
    profile = {
        "location": "Buffalo area",
        "use_location_matching": True,
    }
    ranked = [
        {"id": "weak-local", "tier_order": 2, "location_fit": "local", "sort_index": 0},
        {"id": "strong-far", "tier_order": 0, "location_fit": "far", "sort_index": 1},
        {
            "id": "strong-local-later",
            "tier_order": 0,
            "location_fit": "local",
            "sort_index": 3,
        },
        {
            "id": "strong-local-earlier",
            "tier_order": 0,
            "location_fit": "local",
            "sort_index": 2,
        },
        {
            "id": "moderate-nearby",
            "tier_order": 1,
            "location_fit": "nearby",
            "sort_index": 4,
        },
    ]

    sorted_items = sort_ranked_items(ranked, profile)

    assert [item["id"] for item in sorted_items] == [
        "strong-local-earlier",
        "strong-local-later",
        "strong-far",
        "moderate-nearby",
        "weak-local",
    ]


def test_sort_ranked_items_ignores_location_when_matching_disabled():
    """Verifies that location fit does not affect sort order for statewide users."""
    profile = {
        "location": "Buffalo area",
        "use_location_matching": False,
    }
    ranked = [
        {
            "id": "strong-far-earlier",
            "tier_order": 0,
            "location_fit": "far",
            "sort_index": 1,
        },
        {
            "id": "strong-local-later",
            "tier_order": 0,
            "location_fit": "local",
            "sort_index": 2,
        },
        {"id": "weak-local", "tier_order": 2, "location_fit": "local", "sort_index": 0},
    ]

    sorted_items = sort_ranked_items(ranked, profile)

    assert [item["id"] for item in sorted_items] == [
        "strong-far-earlier",
        "strong-local-later",
        "weak-local",
    ]
