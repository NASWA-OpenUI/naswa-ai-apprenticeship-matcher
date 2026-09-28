from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Callable
from datetime import date
from functools import cache

from botocore.session import get_session

from naswa_matcher.opportunity_detail import build_opportunity_detail

SES_FROM_EMAIL_ENV = "SES_FROM_EMAIL"


def _from_email() -> str:
    """Return the configured SES sender address, if any."""
    return os.getenv(SES_FROM_EMAIL_ENV, "").strip()


def opportunity_email_enabled() -> bool:
    """Return whether opportunity email is configured for this deployment."""
    return bool(_from_email())


def build_opportunity_email(
    opportunity: dict,
    *,
    opportunity_url: str,
    today: date | None = None,
) -> tuple[str, str]:
    """Build the plain-text email for one apprenticeship opportunity."""
    posting = opportunity.get("posting") or {}
    detail = build_opportunity_detail(
        opportunity,
        today=today,
    )

    title = posting.get("jobTitle") or "Apprenticeship opportunity"
    source_title = posting.get("sourceTitle")
    location = posting.get("locationSummary")

    lines = [title]

    if source_title:
        lines.append(source_title)

    if location:
        lines.append(location)

    # Hero metadata
    summary_lines = []

    if detail["application_chip_label"]:
        summary_lines.append(detail["application_chip_label"])

    openings = detail["number_of_openings"]

    if openings:
        summary_lines.append(f"{openings} opening{'' if openings == 1 else 's'}")

    if detail["application_fee"]:
        summary_lines.append(f"${detail['application_fee']} application fee")

    if detail["license_required"]:
        summary_lines.append("Driver's license required")

    if summary_lines:
        lines.extend(["", *summary_lines])

    # Links
    lines.extend(
        [
            "",
            "View in the Registered Apprenticeship Finder",
            opportunity_url,
        ]
    )

    if detail["source_url"]:
        lines.extend(
            [
                "",
                "View original New York State Department of Labor posting",
                detail["source_url"],
            ]
        )

    # How to apply
    application_lines = []

    if posting.get("applicationSummary"):
        application_lines.append(posting["applicationSummary"])

    application_details = [
        ("Website", posting.get("applicationWebsite")),
        ("Email", posting.get("applicationEmail")),
        ("Phone", posting.get("applicationPhone")),
        ("In person", posting.get("applicationInPersonAddress")),
        ("Hours", posting.get("applicationHours")),
    ]

    application_lines.extend(
        f"{label}: {value}" for label, value in application_details if value
    )

    if application_lines:
        lines.extend(["", "How to apply", "", *application_lines])

    # Contact / more information
    contact_lines = []

    if posting.get("contactSummary"):
        contact_lines.append(posting["contactSummary"])

    contact_details = [
        ("Organization", posting.get("contactName")),
        ("Phone", posting.get("contactPhone")),
        ("Email", posting.get("contactEmail")),
        ("Website", posting.get("contactWebsite")),
    ]

    contact_lines.extend(
        f"{label}: {value}" for label, value in contact_details if value
    )

    if contact_lines:
        lines.extend(["", "More information", "", *contact_lines])

    subject = f"{title} — Registered Apprenticeship Finder"
    body = "\n".join(lines).strip() + "\n"

    return subject, body


@cache
def _ses_client():
    """Create the SES client only when email is actually used."""
    return get_session().create_client("sesv2")


def send_opportunity_email(
    recipient: str,
    *,
    subject: str,
    body: str,
) -> None:
    """Send one plain-text opportunity email through Amazon SES."""
    from_email = _from_email()

    if not from_email:
        raise RuntimeError("SES_FROM_EMAIL is not configured")

    _ses_client().send_email(
        FromEmailAddress=from_email,
        Destination={
            "ToAddresses": [recipient],
        },
        Content={
            "Simple": {
                "Subject": {
                    "Data": subject,
                    "Charset": "UTF-8",
                },
                "Body": {
                    "Text": {
                        "Data": body,
                        "Charset": "UTF-8",
                    }
                },
            }
        },
    )


class EmailRateLimiter:
    """Small in-memory rolling-window limiter for opportunity emails."""

    def __init__(
        self,
        *,
        limit: int = 5,
        window_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._attempts: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Record an attempt and return whether it is within the limit."""
        now = self.clock()
        cutoff = now - self.window_seconds

        attempts = self._attempts.setdefault(key, deque())

        while attempts and attempts[0] <= cutoff:
            attempts.popleft()

        if len(attempts) >= self.limit:
            return False

        attempts.append(now)
        return True
