import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from naswa_matcher.sessions import SESSION_MAX_AGE_SECONDS, SessionStore

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class DummyAgent:
    """Small stand-in for Strands Agent so route tests never call AWS."""

    def __init__(self, *args, **kwargs):
        pass

    async def stream_async(self, message):
        yield {"data": f"Echo: {message}"}

    async def invoke_async(self, prompt):
        return "[]"


@pytest.fixture
def opportunities():
    """Load stable test opportunities instead of using the real data directory."""
    fixture_names = [
        "apprenticeship-no-soccode.json",
        "apprenticeship-with-soccode.json",
        "apprenticeship-local-with-soccode.json",
    ]

    return [
        json.loads((FIXTURES_DIR / fixture_name).read_text())
        for fixture_name in fixture_names
    ]


@pytest.fixture
def client(monkeypatch, opportunities, program_groups):
    """FastAPI test client with AWS, DB loading, and live data patched out."""

    monkeypatch.setattr(
        server,
        "session_store",
        SessionStore(
            max_age_seconds=SESSION_MAX_AGE_SECONDS,
            chat_agent_factory=DummyAgent,
        ),
    )

    monkeypatch.setattr(server, "load_db", lambda: None)
    monkeypatch.setattr(server, "all_opportunities", lambda: opportunities)

    monkeypatch.setattr(server, "all_program_groups", lambda: program_groups)

    def fake_get_opportunity(slug: str):
        return next((opp for opp in opportunities if opp["id"] == slug), None)

    monkeypatch.setattr(server, "get_opportunity", fake_get_opportunity)

    def fake_get_program_group(soc_code: str):
        return next(
            (group for group in program_groups if group["socCode"] == soc_code),
            None,
        )

    monkeypatch.setattr(server, "get_program_group", fake_get_program_group)

    with TestClient(server.app) as test_client:
        yield test_client


@pytest.fixture
def program_groups():
    """Return stable SOC-grouped program data for route tests."""
    return [
        {
            "socCode": "47-2111.00",
            "socTitle": "Electricians",
            "programCount": 4,
            "regions": [
                "Western New York",
            ],
            "onet": {
                "description": "Install and maintain electrical systems.",
            },
            "trades": [
                {
                    "tradeName": "Electrician",
                    "displayTradeName": "Electrician",
                    "description": (
                        "Electricians install, maintain, and repair "
                        "electrical wiring and equipment."
                    ),
                    "programCount": 4,
                    "programs": [
                        {
                            "sponsorName": "Buffalo Electrical JAC",
                            "addressCity": "Buffalo",
                            "region": "Western New York",
                            "programLength": 60,
                        },
                        {
                            "sponsorName": "Niagara Electrical Training Alliance",
                            "addressCity": "Niagara Falls",
                            "region": "Western New York",
                            "programLength": 60,
                        },
                        {
                            "sponsorName": "Rochester Electrical JATC",
                            "addressCity": "Rochester",
                            "region": "Finger Lakes",
                            "programLength": 48,
                        },
                        {
                            "sponsorName": "Western New York Electrical Training",
                            "addressCity": "Cheektowaga",
                            "region": "Western New York",
                            "programLength": 48,
                        },
                    ],
                }
            ],
        },
        {
            "socCode": "11-1021.00",
            "socTitle": "General and Operations Managers",
            "programCount": 2,
            "regions": [
                "New York City",
            ],
            "onet": {
                "description": (
                    "Plan, direct, or coordinate organizational operations."
                ),
            },
            "trades": [
                {
                    "tradeName": "Business Operations Associate",
                    "displayTradeName": "Business Operations Associate",
                    "description": (
                        "Business Operations Associates help organizations "
                        "coordinate daily business operations."
                    ),
                    "programCount": 2,
                    "programs": [],
                }
            ],
        },
    ]
