import server


def test_health_route(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_route_renders_chat_page(client):
    response = client.get("/")

    assert response.status_code == 200
    print(response.text)
    assert "Hi there! What’s your name?" in response.text
    assert 'id="chat-form"' in response.text
    assert 'sse-connect="/chat/stream"' in response.text


def test_chat_route_accepts_message_and_returns_user_bubble(client):
    response = client.post("/chat", data={"message": "Paul"})

    assert response.status_code == 200
    assert "Paul" in response.text
    assert "message--user" in response.text
    assert "You" in response.text


def test_chat_reset_route_redirects_to_fresh_chat(client):
    response = client.post("/chat/reset")

    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/"


def test_opportunities_route_renders_fixture_opportunities(client):
    response = client.get("/opportunities")

    assert response.status_code == 200
    assert "Apprenticeship Opportunities" in response.text
    assert "Electrician Apprentice" in response.text
    assert "Sheet Metal Worker Apprentice" in response.text
    assert "Binghamton, NY area" in response.text
    assert "Elmira, NY" in response.text

    # Indirectly verifies the date filter is wired into the route template.
    assert "July 31, 2027" in response.text
    assert "February 28, 2027" in response.text


def test_ranked_opportunities_page_renders_htmx_shell(client):
    response = client.get(
        "/opportunities",
        params=[
            ("ranked", "true"),
            ("interests", "hands-on work"),
            ("interests", "problem solving"),
        ],
    )

    assert response.status_code == 200
    assert "Analyzing your interests" in response.text
    assert 'hx-get="/api/rank-opportunities?' in response.text
    assert "hands-on+work" in response.text
    assert "problem+solving" in response.text


def test_opportunity_detail_route_renders_enriched_opportunity(client):
    response = client.get("/opportunities/electrician-apprentice-fixture")

    assert response.status_code == 200
    assert "Electrician Apprentice" in response.text
    assert "Electricians JAC Fixture" in response.text
    assert "Apply online during the recruitment period." in response.text

    # OES enrichment.
    assert "Entry-level annual wage" in response.text
    assert "$49,249" in response.text
    assert "Western New York" in response.text

    # O*NET enrichment.
    assert "Common work activities" in response.text
    assert "Install electrical components" in response.text
    assert "Key work styles" in response.text
    assert "Dependability" in response.text


def test_opportunity_detail_route_renders_non_enriched_opportunity(client):
    response = client.get("/opportunities/sheet-metal-worker-apprentice-fixture")

    assert response.status_code == 200
    assert "Sheet Metal Worker Apprentice" in response.text
    assert "Area Sheet Metal Workers Fixture" in response.text
    assert "Obtain an application and submit it by the deadline." in response.text

    # This fixture has no OES/O*NET enrichment.
    assert "Entry-level annual wage" not in response.text
    assert "Common work activities" not in response.text
    assert "Why this matches you" not in response.text


def test_opportunity_detail_route_returns_404_for_unknown_slug(client):
    response = client.get("/opportunities/not-a-real-slug")

    assert response.status_code == 404


def test_rank_opportunities_route_uses_mocked_scores(client, monkeypatch):
    async def fake_score_jobs(interests, onet_jobs):
        assert interests == ["hands-on work", "problem solving"]
        assert [job["id"] for job in onet_jobs] == ["electrician-apprentice-fixture"]

        return [
            {
                "id": "electrician-apprentice-fixture",
                "tier": "Strong",
                "explanation": "Good match for hands-on troubleshooting work.",
            }
        ]

    monkeypatch.setattr(server, "_score_jobs", fake_score_jobs)

    response = client.get(
        "/api/rank-opportunities",
        params=[
            ("interests", "hands-on work"),
            ("interests", "problem solving"),
        ],
    )

    assert response.status_code == 200

    assert "Matched to your interests" in response.text
    assert "hands-on work" in response.text
    assert "problem solving" in response.text

    # Ranked O*NET-backed opportunity.
    assert "Strong" in response.text
    assert "Electrician Apprentice" in response.text
    assert "Good match for hands-on troubleshooting work." in response.text

    # Non-O*NET opportunity still appears as unranked.
    assert "More Opportunities" in response.text
    assert "Sheet Metal Worker Apprentice" in response.text
