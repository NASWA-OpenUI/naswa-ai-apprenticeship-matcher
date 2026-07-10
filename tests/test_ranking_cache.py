import json

from naswa_matcher.ranking_cache import RankingCache, RankingCacheEntry


def make_profile(**overrides) -> dict:
    profile = {
        "name": "Taylor",
        "likes": ["math", "electronics"],
        "dislikes": ["desk work"],
        "location": "Buffalo",
        "transportation": "car",
        "use_location_matching": True,
        "confirmed": True,
    }
    profile.update(overrides)
    return profile


def test_equivalent_cleaned_profiles_generate_same_key():
    cache = RankingCache(max_age_seconds=100)

    uncleaned = make_profile(
        name="Ignored Name",
        likes=[" math ", "electronics "],
        dislikes=[" desk work "],
        location=" Buffalo ",
        transportation=" car ",
        confirmed=False,
    )
    cleaned = make_profile()

    assert cache.key_for(uncleaned) == cache.key_for(cleaned)


def test_profile_fields_that_do_not_affect_ranking_are_ignored():
    cache = RankingCache(max_age_seconds=100)

    first = make_profile(
        name="Taylor",
        confirmed=False,
    )
    second = make_profile(
        name="Morgan",
        confirmed=True,
    )

    assert cache.key_for(first) == cache.key_for(second)


def test_list_order_is_preserved_in_cache_key():
    cache = RankingCache(max_age_seconds=100)

    first = make_profile(likes=["math", "electronics"])
    second = make_profile(likes=["electronics", "math"])

    assert cache.key_for(first) != cache.key_for(second)


def test_complete_fresh_entry_is_returned():
    now = [100.0]
    cache = RankingCache(
        max_age_seconds=10,
        clock=lambda: now[0],
    )
    profile = make_profile()

    cache.put(
        profile,
        RankingCacheEntry(
            profile=profile,
            ranked=[{"id": "electrician"}],
            completed_jobs=1,
            total_jobs=1,
            created_at=95.0,
            is_complete=True,
        ),
    )

    cached = cache.get(profile)

    assert cached is not None
    assert cached.ranked == [{"id": "electrician"}]
    assert cached.completed_jobs == 1
    assert cached.total_jobs == 1


def test_put_stores_normalized_profile_snapshot():
    cache = RankingCache(max_age_seconds=100)
    profile = make_profile(
        likes=[" math ", " electronics "],
        location=" Buffalo ",
    )

    cache.put(
        profile,
        RankingCacheEntry(
            profile=profile,
            is_complete=True,
        ),
    )

    cached = cache.get(profile)

    assert cached is not None
    assert cached.profile == {
        "likes": ["math", "electronics"],
        "dislikes": ["desk work"],
        "location": "Buffalo",
        "transportation": "car",
        "use_location_matching": True,
    }


def test_expired_entry_is_rejected_and_removed():
    now = [100.0]
    cache = RankingCache(
        max_age_seconds=10,
        clock=lambda: now[0],
    )
    profile = make_profile()

    cache.put(
        profile,
        RankingCacheEntry(
            profile=profile,
            created_at=89.0,
            is_complete=True,
        ),
    )

    key = cache.key_for(profile)

    assert key in cache.entries
    assert cache.get(profile) is None
    assert key not in cache.entries


def test_incomplete_entry_is_rejected():
    cache = RankingCache(
        max_age_seconds=100,
        clock=lambda: 100.0,
    )
    profile = make_profile()

    cache.put(
        profile,
        RankingCacheEntry(
            profile=profile,
            created_at=100.0,
            is_complete=False,
        ),
    )

    assert cache.get(profile) is None


def test_cache_version_change_invalidates_existing_key():
    entries = {}
    profile = make_profile()

    original_cache = RankingCache(
        max_age_seconds=100,
        version="rank-cache-v1",
        entries=entries,
        clock=lambda: 100.0,
    )
    original_cache.put(
        profile,
        RankingCacheEntry(
            profile=profile,
            created_at=100.0,
            is_complete=True,
        ),
    )

    updated_cache = RankingCache(
        max_age_seconds=100,
        version="rank-cache-v2",
        entries=entries,
        clock=lambda: 100.0,
    )

    assert updated_cache.get(profile) is None


def test_false_location_matching_is_preserved_in_key():
    cache = RankingCache(max_age_seconds=100)
    profile = make_profile(use_location_matching=False)

    payload = json.loads(cache.key_for(profile))

    assert payload["profile"]["use_location_matching"] is False


def test_clear_removes_all_entries():
    cache = RankingCache(max_age_seconds=100)
    profile = make_profile()

    cache.put(
        profile,
        RankingCacheEntry(
            profile=profile,
            is_complete=True,
        ),
    )

    cache.clear()

    assert cache.entries == {}
