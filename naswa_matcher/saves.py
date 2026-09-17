from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from dataclasses import dataclass

from starlette.responses import Response

SAVES_COOKIE_NAME = "naswa_saves"
SAVES_MAX_AGE_SECONDS = 60 * 60 * 24 * 90  # 90 days
SAVES_MAX_ITEMS = 35

_SAVES_VERSION = "v1"
_ENTRY_SEPARATOR = "~"
_SIGNATURE_SEPARATOR = "."
_OPPORTUNITY_PREFIX = "o:"

_OPPORTUNITY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,199}$")

_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
_FALSE_ENV_VALUES = {"0", "false", "no", "off"}


class SaveLimitReached(ValueError):
    """Raised when the browser has reached the saved-item limit."""


@dataclass(frozen=True)
class SavedItems:
    """Saved apprenticeship items stored in the browser cookie."""

    opportunity_ids: tuple[str, ...] = ()

    @property
    def total_count(self) -> int:
        return len(self.opportunity_ids)

    @property
    def has_items(self) -> bool:
        return bool(self.opportunity_ids)

    def has_opportunity(self, opportunity_id: str) -> bool:
        return opportunity_id in self.opportunity_ids

    def with_opportunity(self, opportunity_id: str) -> "SavedItems":
        if self.has_opportunity(opportunity_id):
            return self

        if self.total_count >= SAVES_MAX_ITEMS:
            raise SaveLimitReached(
                f"You can save up to {SAVES_MAX_ITEMS} opportunities."
            )

        return SavedItems(
            opportunity_ids=(
                *self.opportunity_ids,
                opportunity_id,
            )
        )

    def without_opportunity(self, opportunity_id: str) -> "SavedItems":
        if not self.has_opportunity(opportunity_id):
            return self

        return SavedItems(
            opportunity_ids=tuple(
                saved_id
                for saved_id in self.opportunity_ids
                if saved_id != opportunity_id
            )
        )


def _saves_cookie_secure() -> bool:
    """
    Use SAVES_COOKIE_SECURE when explicitly configured.

    Otherwise follow SESSION_COOKIE_SECURE so the save cookie behaves like the
    application's existing session cookie.
    """
    value = (
        os.getenv(
            "SAVES_COOKIE_SECURE",
            os.getenv("SESSION_COOKIE_SECURE", "false"),
        )
        .strip()
        .lower()
    )

    if value in _TRUE_ENV_VALUES:
        return True

    if value in _FALSE_ENV_VALUES:
        return False

    raise ValueError(
        "SAVES_COOKIE_SECURE must be one of: " "true, false, 1, 0, yes, no, on, or off."
    )


def _cookie_secret() -> bytes:
    secret = os.getenv("SAVES_COOKIE_SECRET", "").strip()
    print("SECRET", secret)

    if not secret:
        raise RuntimeError(
            "SAVES_COOKIE_SECRET must be configured before saved "
            "opportunities can be stored."
        )

    return secret.encode("utf-8")


def _clean_opportunity_id(value: str) -> str | None:
    value = value.strip()

    if not value:
        return None

    if not _OPPORTUNITY_ID_PATTERN.fullmatch(value):
        return None

    return value


def _sign(payload: str) -> str:
    digest = hmac.new(
        _cookie_secret(),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _signed_value(payload: str) -> str:
    return f"{payload}{_SIGNATURE_SEPARATOR}{_sign(payload)}"


def serialize_saves_cookie(saved: SavedItems) -> str:
    entries = [
        f"{_OPPORTUNITY_PREFIX}{opportunity_id}"
        for opportunity_id in saved.opportunity_ids
    ]

    payload = f"{_SAVES_VERSION}:" f"{_ENTRY_SEPARATOR.join(entries)}"

    return _signed_value(payload)


def parse_saves_cookie(value: str | None) -> SavedItems:
    """
    Parse and verify the saved-items cookie.

    Invalid, tampered, unsupported, or malformed values degrade to an empty
    collection rather than raising during normal request handling.
    """
    if not value:
        return SavedItems()

    try:
        payload, supplied_signature = value.rsplit(
            _SIGNATURE_SEPARATOR,
            1,
        )
    except ValueError:
        return SavedItems()

    try:
        expected_signature = _sign(payload)
    except RuntimeError:
        # Configuration errors should remain visible to the application rather
        # than being mistaken for malformed user data.
        raise

    if not hmac.compare_digest(
        supplied_signature,
        expected_signature,
    ):
        return SavedItems()

    version_prefix = f"{_SAVES_VERSION}:"

    if not payload.startswith(version_prefix):
        return SavedItems()

    encoded_entries = payload[len(version_prefix) :]

    if not encoded_entries:
        return SavedItems()

    opportunity_ids: list[str] = []
    seen: set[str] = set()

    for entry in encoded_entries.split(_ENTRY_SEPARATOR):
        if len(opportunity_ids) >= SAVES_MAX_ITEMS:
            break

        if not entry.startswith(_OPPORTUNITY_PREFIX):
            # Future/unknown namespaces are ignored for now.
            continue

        opportunity_id = _clean_opportunity_id(entry[len(_OPPORTUNITY_PREFIX) :])

        if opportunity_id is None:
            continue

        if opportunity_id in seen:
            continue

        seen.add(opportunity_id)
        opportunity_ids.append(opportunity_id)

    return SavedItems(opportunity_ids=tuple(opportunity_ids))


def sync_saves_cookie(
    response: Response,
    saved: SavedItems,
    *,
    had_cookie: bool,
) -> None:
    """
    Persist the current save state.

    Existing non-empty cookies are re-issued on each application request,
    giving them a rolling 90-day lifetime. Empty collections do not create a
    cookie; if one previously existed, it is deleted.
    """
    secure = _saves_cookie_secure()

    if saved.has_items:
        response.set_cookie(
            key=SAVES_COOKIE_NAME,
            value=serialize_saves_cookie(saved),
            max_age=SAVES_MAX_AGE_SECONDS,
            httponly=True,
            samesite="lax",
            secure=secure,
            path="/",
        )
        return

    if had_cookie:
        response.delete_cookie(
            key=SAVES_COOKIE_NAME,
            httponly=True,
            samesite="lax",
            secure=secure,
            path="/",
        )
