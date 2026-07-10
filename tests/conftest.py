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
def client(monkeypatch, opportunities):
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

    def fake_get_opportunity(slug: str):
        return next((opp for opp in opportunities if opp["id"] == slug), None)

    monkeypatch.setattr(server, "get_opportunity", fake_get_opportunity)

    with TestClient(server.app) as test_client:
        yield test_client
