from datetime import date

import pytest

import naswa_matcher.opportunity_email as opportunity_email
from naswa_matcher.opportunity_email import (
    EmailRateLimiter,
    build_opportunity_email,
    opportunity_email_enabled,
    send_opportunity_email,
)


@pytest.fixture
def opportunity():
    return {
        "id": "electrician-apprentice",
        "posting": {
            "jobTitle": "Electrician Apprentice",
            "sourceTitle": "Electricians JAC",
            "numberOfOpenings": 2,
            "locationSummary": "Binghamton, NY area",
            "applicationStartDate": "2027-06-01",
            "applicationEndDate": "2027-07-31",
            "applicationSummary": ("Apply online during the recruitment period."),
            "applicationWebsite": "https://example.org/apply",
            "applicationEmail": "apply@example.org",
            "applicationPhone": "(555) 555-0100",
            "applicationInPersonAddress": None,
            "applicationHours": None,
            "applicationFee": None,
            "transportationRequirement": None,
            "allRequirements": [
                "Must be at least 18 years old.",
                "Must have a high school diploma or equivalent.",
            ],
            "contactSummary": (
                "Contact the apprenticeship committee for more information."
            ),
            "contactName": "Electricians JAC",
            "contactPhone": "(555) 555-0200",
            "contactEmail": "info@example.org",
            "contactWebsite": "https://example.org",
            "sourceUrl": "https://dol.ny.gov/example-opportunity",
        },
        "jobDescription": {
            "displayJobTitle": "Electrician",
            "description": (
                "Electricians install, maintain, and repair electrical systems."
            ),
        },
        "onet": {
            "description": "Fallback O*NET description.",
            "detailed_work_activities": {
                "data": {
                    "activity": [
                        {"title": "Install electrical components."},
                        {"title": "Inspect electrical systems."},
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


def test_opportunity_email_disabled_without_sender(monkeypatch):
    monkeypatch.delenv("SES_FROM_EMAIL", raising=False)

    assert opportunity_email_enabled() is False


def test_opportunity_email_disabled_with_blank_sender(monkeypatch):
    monkeypatch.setenv("SES_FROM_EMAIL", "   ")

    assert opportunity_email_enabled() is False


def test_opportunity_email_enabled_with_sender(monkeypatch):
    monkeypatch.setenv(
        "SES_FROM_EMAIL",
        "notifications@nofo.rodeo",
    )

    assert opportunity_email_enabled() is True


def test_build_opportunity_email(opportunity):
    subject, body = build_opportunity_email(
        opportunity,
        opportunity_url=("https://example.org/opportunities/electrician-apprentice"),
        today=date(2027, 7, 1),
    )

    assert subject == ("Electrician Apprentice — Registered Apprenticeship Finder")

    assert "Electrician Apprentice" in body
    assert "Electricians JAC" in body
    assert "Binghamton, NY area" in body

    assert "Apply by Jul 31, 2027" in body
    assert "2 openings" in body

    assert "Electricians install, maintain, and repair electrical systems." in body

    assert "What you might do day to day" in body
    assert "- Install electrical components." in body
    assert "- Inspect electrical systems." in body

    assert "Helpful traits for this job" in body
    assert "- Attention to Detail" in body
    assert "- Dependability" in body

    assert "How to apply" in body
    assert "Apply online during the recruitment period." in body
    assert "Website: https://example.org/apply" in body
    assert "Email: apply@example.org" in body

    assert "Job requirements" in body
    assert "- Must be at least 18 years old." in body

    assert "More information" in body
    assert "Phone: (555) 555-0200" in body
    assert "Email: info@example.org" in body

    assert "https://example.org/opportunities/electrician-apprentice" in body
    assert "https://dol.ny.gov/example-opportunity" in body


def test_build_opportunity_email_handles_missing_optional_data():
    opportunity = {
        "id": "simple-apprentice",
        "posting": {
            "jobTitle": "Simple Apprentice",
        },
    }

    subject, body = build_opportunity_email(
        opportunity,
        opportunity_url="https://example.org/opportunities/simple-apprentice",
        today=date(2027, 7, 1),
    )

    assert subject == ("Simple Apprentice — Registered Apprenticeship Finder")
    assert "Simple Apprentice" in body
    assert "https://example.org/opportunities/simple-apprentice" in body

    assert "None" not in body
    assert "Job requirements" not in body
    assert "How to apply" not in body


def test_send_opportunity_email_uses_ses(monkeypatch):
    class FakeSESClient:
        def __init__(self):
            self.kwargs = None

        def send_email(self, **kwargs):
            self.kwargs = kwargs

    client = FakeSESClient()

    monkeypatch.setenv(
        "SES_FROM_EMAIL",
        "notifications@nofo.rodeo",
    )
    monkeypatch.setattr(
        opportunity_email,
        "_ses_client",
        lambda: client,
    )

    send_opportunity_email(
        "person@example.org",
        subject="Test subject",
        body="Test body",
    )

    assert client.kwargs == {
        "FromEmailAddress": "notifications@nofo.rodeo",
        "Destination": {
            "ToAddresses": ["person@example.org"],
        },
        "Content": {
            "Simple": {
                "Subject": {
                    "Data": "Test subject",
                    "Charset": "UTF-8",
                },
                "Body": {
                    "Text": {
                        "Data": "Test body",
                        "Charset": "UTF-8",
                    }
                },
            }
        },
    }


def test_send_opportunity_email_requires_configuration(monkeypatch):
    monkeypatch.delenv("SES_FROM_EMAIL", raising=False)

    def unexpected_client():
        raise AssertionError("SES client should not be created")

    monkeypatch.setattr(
        opportunity_email,
        "_ses_client",
        unexpected_client,
    )

    with pytest.raises(
        RuntimeError,
        match="SES_FROM_EMAIL is not configured",
    ):
        send_opportunity_email(
            "person@example.org",
            subject="Test subject",
            body="Test body",
        )


def test_email_rate_limiter_allows_ten_attempts_per_minute():
    now = [100.0]

    limiter = EmailRateLimiter(
        limit=10,
        window_seconds=60,
        clock=lambda: now[0],
    )

    for _ in range(10):
        assert limiter.allow("visitor-1") is True

    assert limiter.allow("visitor-1") is False


def test_email_rate_limiter_resets_after_window():
    now = [100.0]

    limiter = EmailRateLimiter(
        limit=2,
        window_seconds=60,
        clock=lambda: now[0],
    )

    assert limiter.allow("visitor-1") is True
    assert limiter.allow("visitor-1") is True
    assert limiter.allow("visitor-1") is False

    now[0] = 159.9

    assert limiter.allow("visitor-1") is False

    now[0] = 160.0

    assert limiter.allow("visitor-1") is True


def test_email_rate_limiter_tracks_visitors_separately():
    limiter = EmailRateLimiter(
        limit=1,
        clock=lambda: 100.0,
    )

    assert limiter.allow("visitor-1") is True
    assert limiter.allow("visitor-1") is False

    assert limiter.allow("visitor-2") is True
