import pytest
from starlette.responses import Response

import naswa_matcher.saves as saves
from naswa_matcher.saves import (
    SAVES_COOKIE_NAME,
    SAVES_MAX_AGE_SECONDS,
    SAVES_MAX_ITEMS,
    SavedItems,
    SaveLimitReached,
    parse_saves_cookie,
    serialize_saves_cookie,
    sync_saves_cookie,
)


@pytest.fixture(autouse=True)
def saves_secret(monkeypatch):
    monkeypatch.setenv(
        "SAVES_COOKIE_SECRET",
        "test-saves-cookie-secret",
    )
    monkeypatch.setenv(
        "SAVES_COOKIE_SECURE",
        "false",
    )


def test_cookie_round_trip():
    original = SavedItems(
        opportunity_ids=(
            "electrician-apprentice",
            "welder-apprentice",
        )
    )

    encoded = serialize_saves_cookie(original)
    decoded = parse_saves_cookie(encoded)

    assert decoded == original


def test_tampered_cookie_returns_empty():
    original = SavedItems(opportunity_ids=("electrician-apprentice",))

    encoded = serialize_saves_cookie(original)
    tampered = encoded.replace(
        "electrician",
        "plumber",
    )

    assert parse_saves_cookie(tampered) == SavedItems()


def test_unknown_version_returns_empty():
    payload = "v2:o:electrician-apprentice"
    value = saves._signed_value(payload)

    assert parse_saves_cookie(value) == SavedItems()


def test_unknown_entry_type_is_ignored():
    payload = (
        "v1:" "o:electrician-apprentice" "~p:future-program" "~o:welder-apprentice"
    )
    value = saves._signed_value(payload)

    parsed = parse_saves_cookie(value)

    assert parsed.opportunity_ids == (
        "electrician-apprentice",
        "welder-apprentice",
    )


def test_malformed_entries_are_ignored():
    payload = (
        "v1:"
        "o:electrician-apprentice"
        "~bad-entry"
        "~o:"
        "~o:not/allowed"
        "~o:welder-apprentice"
    )
    value = saves._signed_value(payload)

    parsed = parse_saves_cookie(value)

    assert parsed.opportunity_ids == (
        "electrician-apprentice",
        "welder-apprentice",
    )


def test_duplicate_entries_are_deduplicated():
    payload = "v1:" "o:electrician-apprentice" "~o:electrician-apprentice"
    value = saves._signed_value(payload)

    parsed = parse_saves_cookie(value)

    assert parsed.opportunity_ids == ("electrician-apprentice",)


def test_parser_enforces_item_cap():
    ids = tuple(f"opportunity-{index}" for index in range(SAVES_MAX_ITEMS + 5))

    payload = "v1:" + "~".join(f"o:{opportunity_id}" for opportunity_id in ids)

    parsed = parse_saves_cookie(saves._signed_value(payload))

    assert parsed.opportunity_ids == ids[:SAVES_MAX_ITEMS]


def test_saving_same_opportunity_is_idempotent():
    saved = SavedItems(opportunity_ids=("electrician-apprentice",))

    updated = saved.with_opportunity("electrician-apprentice")

    assert updated is saved


def test_save_limit_is_35():
    saved = SavedItems(
        opportunity_ids=tuple(
            f"opportunity-{index}" for index in range(SAVES_MAX_ITEMS)
        )
    )

    with pytest.raises(SaveLimitReached):
        saved.with_opportunity("one-more")


def test_unsave_removes_opportunity():
    saved = SavedItems(
        opportunity_ids=(
            "electrician-apprentice",
            "welder-apprentice",
        )
    )

    updated = saved.without_opportunity("electrician-apprentice")

    assert updated.opportunity_ids == ("welder-apprentice",)


def test_sync_saves_cookie_sets_expected_cookie():
    response = Response()

    sync_saves_cookie(
        response,
        SavedItems(opportunity_ids=("electrician-apprentice",)),
        had_cookie=False,
    )

    cookie = response.headers["set-cookie"]

    assert f"{SAVES_COOKIE_NAME}=" in cookie
    assert f"Max-Age={SAVES_MAX_AGE_SECONDS}" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie
    assert "SameSite=lax" in cookie


def test_empty_saves_do_not_create_cookie():
    response = Response()

    sync_saves_cookie(
        response,
        SavedItems(),
        had_cookie=False,
    )

    assert "set-cookie" not in response.headers


def test_empty_saves_delete_existing_cookie():
    response = Response()

    sync_saves_cookie(
        response,
        SavedItems(),
        had_cookie=True,
    )

    cookie = response.headers["set-cookie"]

    assert f"{SAVES_COOKIE_NAME}=" in cookie
    assert "Max-Age=0" in cookie
