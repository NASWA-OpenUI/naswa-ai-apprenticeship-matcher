from naswa_matcher.location_matching import (
    LOCATION_FIT_ORDER,
    cap_tier_by_location,
    infer_location_groups,
    job_location_text,
    location_fit,
    should_use_location_matching,
    text_mentions_term,
)


def test_text_mentions_term_matches_full_words_and_phrases():
    """Verifies that location term matching works for full words and common
    multi-word place names."""
    assert text_mentions_term("near niagara falls, ny", "niagara falls")
    assert text_mentions_term("long island city, ny area", "long island city")
    assert text_mentions_term("st. lawrence county", "st. lawrence")


def test_text_mentions_term_does_not_match_inside_other_words():
    """Verifies that location matching does not produce false positives when a
    place name only appears inside a longer unrelated word."""
    assert not text_mentions_term("orangeville township", "orange")
    assert not text_mentions_term("newyork city", "new york")
    assert not text_mentions_term("schenectadyville", "schenectady")


def test_infer_location_groups_returns_empty_set_for_missing_text():
    """Verifies that missing or blank location text produces no inferred
    location groups rather than raising an error."""
    assert infer_location_groups(None) == set()
    assert infer_location_groups("") == set()


def test_infer_location_groups_identifies_user_location():
    """Verifies that common user-entered cities or regional phrases map to the
    expected broad New York location groups."""
    assert infer_location_groups("Niagara Falls, NY") == {"western"}
    assert infer_location_groups("Buffalo and the surrounding area") == {"western"}
    assert infer_location_groups("near Rochester") == {"finger_lakes"}


def test_infer_location_groups_can_identify_multiple_regions():
    """Verifies that text mentioning several New York regions can infer more
    than one location group."""
    text = "Finger Lakes, Southern Tier, and Western regions of New York State"
    assert infer_location_groups(text) == {
        "finger_lakes",
        "southern_tier",
        "western",
    }


def test_infer_location_groups_identifies_city_based_job_locations():
    """Verifies that job location summaries using city names map to the correct
    broad New York location groups."""
    assert infer_location_groups("Long Island City, NY area") == {"nyc_long_island"}
    assert infer_location_groups("Albany, NY area") == {"capital"}
    assert infer_location_groups("Watertown, NY area") == {"north_country"}
    assert infer_location_groups("White Plains, NY area") == {"hudson_valley"}


def test_should_use_location_matching_defaults_to_true():
    """Verifies that location matching is enabled by default unless the profile
    explicitly disables it."""
    assert should_use_location_matching({}) is True
    assert should_use_location_matching({"use_location_matching": True}) is True


def test_should_use_location_matching_can_be_disabled():
    """Verifies that a boolean false profile value disables location matching."""
    assert should_use_location_matching({"use_location_matching": False}) is False


def test_should_use_location_matching_treats_string_false_as_disabled():
    """Verifies that false-like string values from query params or serialized
    profiles also disable location matching."""
    assert should_use_location_matching({"use_location_matching": "false"}) is False
    assert should_use_location_matching({"use_location_matching": "False"}) is False
    assert should_use_location_matching({"use_location_matching": "0"}) is False
    assert should_use_location_matching({"use_location_matching": "no"}) is False


def test_should_use_location_matching_treats_other_values_as_enabled():
    """Verifies that true-like, missing, or null-ish values keep location
    matching enabled by default."""
    assert should_use_location_matching({"use_location_matching": "true"}) is True
    assert should_use_location_matching({"use_location_matching": "yes"}) is True
    assert should_use_location_matching({"use_location_matching": None}) is True


def make_job(
    *,
    location_summary: str | None = None,
    regions: list[str] | None = None,
    all_requirements: list[str] | None = None,
) -> dict:
    """Builds a minimal posting-shaped job fixture for testing location matching
    without depending on full opportunity JSON records."""
    return {
        "posting": {
            "locationSummary": location_summary,
            "regions": regions or [],
            "allRequirements": all_requirements or [],
        }
    }


def test_job_location_text_combines_location_summary_regions_and_requirements():
    """Verifies that job location text combines all relevant posting fields used
    to infer the job's broad location group."""
    job = make_job(
        location_summary="Orchard Park, NY area",
        regions=["Western"],
        all_requirements=[
            "Must have reliable transportation.",
            "Jurisdiction includes Erie County and Niagara County.",
        ],
    )

    text = job_location_text(job)

    assert "Orchard Park, NY area" in text
    assert "Western" in text
    assert "Jurisdiction includes Erie County and Niagara County." in text


def test_job_location_text_handles_non_list_regions_and_requirements():
    """Verifies that unexpected string values for regions or requirements are
    still included in the searchable location text."""
    job = {
        "posting": {
            "locationSummary": "Rochester, NY area",
            "regions": "Finger Lakes",
            "allRequirements": "Must have reliable transportation.",
        }
    }
    text = job_location_text(job)
    assert "Rochester, NY area" in text
    assert "Finger Lakes" in text
    assert "Must have reliable transportation." in text


def test_location_fit_returns_unknown_when_user_location_is_missing():
    """Verifies that location fit is unknown when the user has not provided a
    usable location."""
    profile = {"location": None}
    job = make_job(location_summary="Buffalo, NY area")
    assert location_fit(profile, job) == "unknown"


def test_location_fit_returns_unknown_when_job_location_cannot_be_inferred():
    """Verifies that location fit is unknown when the job text does not map to
    any known New York location group."""
    profile = {"location": "Niagara Falls, NY"}
    job = make_job(location_summary="Various job sites")
    assert location_fit(profile, job) == "unknown"


def test_location_fit_returns_local_when_user_and_job_region_overlap():
    """Verifies that a job is local when the user's inferred group overlaps with
    one of the job's inferred groups."""
    profile = {"location": "Niagara Falls, NY"}
    job = make_job(
        location_summary="Finger Lakes and Western New York regions",
        regions=["Finger Lakes", "Western"],
    )
    assert location_fit(profile, job) == "local"


def test_location_fit_uses_all_requirements_to_find_local_match():
    """Verifies that residency or jurisdiction text in requirements can provide
    enough location evidence to identify a local match."""
    profile = {"location": "Niagara Falls, NY"}
    job = make_job(
        location_summary="Local Union jurisdiction",
        all_requirements=[
            "Must reside in Cattaraugus, Chautauqua, Erie, Niagara, or Wyoming Counties.",
        ],
    )
    assert location_fit(profile, job) == "local"


def test_location_fit_returns_nearby_for_neighboring_region():
    """Verifies that jobs in configured neighboring regions are classified as
    nearby rather than far."""
    profile = {"location": "Niagara Falls, NY"}
    job = make_job(location_summary="Rochester, NY area")
    assert location_fit(profile, job) == "nearby"


def test_location_fit_returns_far_for_non_neighboring_region():
    """Verifies that jobs outside the user's region and neighboring regions are
    classified as far."""
    profile = {"location": "Niagara Falls, NY"}
    job = make_job(location_summary="Long Island City, NY area")
    assert location_fit(profile, job) == "far"


def test_location_fit_returns_local_when_job_spans_many_regions_including_user_region():
    """Verifies that multi-region jobs are local when one of the listed regions
    includes the user's region."""
    profile = {"location": "Niagara Falls, NY"}
    job = make_job(
        location_summary=(
            "Capital District, Central, Finger Lakes, Mohawk Valley, "
            "North Country, Southern Tier, and Western New York"
        ),
        regions=[
            "Capital District",
            "Central",
            "Finger Lakes",
            "Mohawk Valley",
            "North Country",
            "Southern Tier",
            "Western",
        ],
    )
    assert location_fit(profile, job) == "local"


def test_cap_tier_by_location_downgrades_strong_nearby_or_far_matches():
    """Verifies that Strong model scores are capped to Moderate when location
    fit is nearby or far."""
    assert cap_tier_by_location("Strong", "nearby") == "Moderate"
    assert cap_tier_by_location("Strong", "far") == "Moderate"


def test_cap_tier_by_location_keeps_strong_local_and_unknown_matches():
    """Verifies that Strong model scores are preserved for local matches and
    for unknown location fit."""
    assert cap_tier_by_location("Strong", "local") == "Strong"
    assert cap_tier_by_location("Strong", "unknown") == "Strong"


def test_cap_tier_by_location_does_not_upgrade_moderate_or_weak_matches():
    """Verifies that the location cap can downgrade Strong matches, but never
    upgrades Moderate or Weak model scores."""
    assert cap_tier_by_location("Moderate", "local") == "Moderate"
    assert cap_tier_by_location("Weak", "local") == "Weak"
    assert cap_tier_by_location("Moderate", "far") == "Moderate"
    assert cap_tier_by_location("Weak", "far") == "Weak"


def test_cap_tier_by_location_normalizes_unexpected_tiers_to_weak():
    """Verifies that invalid or missing model tiers are normalized to Weak so
    unexpected model output does not break ranking."""
    assert cap_tier_by_location(None, "local") == "Weak"
    assert cap_tier_by_location("Excellent", "local") == "Weak"


def test_location_fit_order_sorts_local_before_nearby_unknown_and_far():
    """Verifies that the configured location-fit sort order prioritizes local
    matches before nearby, unknown, and far matches."""
    assert LOCATION_FIT_ORDER["local"] < LOCATION_FIT_ORDER["nearby"]
    assert LOCATION_FIT_ORDER["nearby"] < LOCATION_FIT_ORDER["unknown"]
    assert LOCATION_FIT_ORDER["unknown"] < LOCATION_FIT_ORDER["far"]