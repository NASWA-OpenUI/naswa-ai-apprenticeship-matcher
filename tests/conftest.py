import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server

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
    ]

    return [
        json.loads((FIXTURES_DIR / fixture_name).read_text())
        for fixture_name in fixture_names
    ]


@pytest.fixture
def client(monkeypatch, opportunities):
    """FastAPI test client with AWS, DB loading, and live data patched out."""

    monkeypatch.setattr(server, "Agent", DummyAgent)
    monkeypatch.setattr(server, "load_db", lambda: None)
    monkeypatch.setattr(server, "all_opportunities", lambda: opportunities)

    def fake_get_opportunity(slug: str):
        return next((opp for opp in opportunities if opp["id"] == slug), None)

    monkeypatch.setattr(server, "get_opportunity", fake_get_opportunity)

    # Keep route tests isolated from sessions created by previous tests.
    server._sessions.clear()

    with TestClient(server.app) as test_client:
        yield test_client

    server._sessions.clear()
