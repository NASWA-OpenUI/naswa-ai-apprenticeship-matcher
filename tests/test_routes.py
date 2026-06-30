import server


def test_health_route(client):
    """Verifies that the health check endpoint returns 200 and the expected
    simple JSON response used by deployment health checks."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_route_renders_index(client):
    """Verifies that the landing page renders successfully with the expected
    hero content and links into the chat flow."""
    response = client.get("/")

    assert response.status_code == 200
    assert "Get matched with a career you’ll love" in response.text
    assert 'href="/chat"' in response.text
    assert 'class="landing-page"' in response.text


def test_chat_get_route_renders_chat_page(client):
    """Verifies that the chat page renders the initial assistant message,
    chat form, and SSE connection for streaming responses."""
    response = client.get("/chat")

    assert response.status_code == 200
    assert "What’s your name?" in response.text
    assert 'id="chat-form"' in response.text
    assert 'sse-connect="/chat/stream"' in response.text


def test_chat_route_accepts_message_and_returns_user_bubble(client):
    """Verifies that posting a chat message returns the rendered user message
    bubble without needing to wait for the assistant stream."""
    response = client.post("/chat", data={"message": "Paul"})

    assert response.status_code == 200
    assert "Paul" in response.text
    assert "message--user" in response.text
    assert "You" in response.text


def test_chat_reset_route_redirects_to_fresh_chat(client):
    """Verifies that resetting the chat clears the session state and tells HTMX
    to redirect the browser back to the fresh chat page."""
    response = client.post("/chat/reset")

    assert response.status_code == 204
    assert response.headers["HX-Redirect"] == "/chat"


def test_opportunities_route_renders_fixture_opportunities(client):
    """Verifies that the unranked opportunities page renders fixture jobs and
    displays their location and application close dates."""
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


def test_opportunity_detail_route_renders_enriched_opportunity(client):
    """Verifies that an enriched opportunity detail page includes posting data,
    wage data from OES, and work information from O*NET."""
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
    """Verifies that a non-enriched opportunity detail page still renders, but
    does not show OES, O*NET, or match-specific sections."""
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
    """Verifies that requesting an unknown opportunity slug returns a 404
    instead of rendering an empty or broken detail page."""
    response = client.get("/opportunities/not-a-real-slug")

    assert response.status_code == 404


def test_rank_opportunities_stream_caps_non_local_strong_matches(client, monkeypatch):
    """Verifies that the streaming rank endpoint caps far/non-local Strong
    model scores to Moderate when location matching is enabled."""

    async def fake_score_jobs(profile, onet_jobs):
        assert profile["likes"] == ["hands-on work", "problem solving"]
        assert profile["location"] == "Buffalo area"

        job_ids = {job["id"] for job in onet_jobs}

        assert "electrician-apprentice-fixture" in job_ids
        assert "boilermaker-apprentice-local-fixture" in job_ids

        return [
            {
                "id": "electrician-apprentice-fixture",
                "tier": "Strong",
                "explanation": "Good match for hands-on troubleshooting work.",
            },
            {
                "id": "boilermaker-apprentice-local-fixture",
                "tier": "Strong",
                "explanation": "Good local match for fixing mechanical equipment.",
            },
        ]

    monkeypatch.setattr(server, "_score_jobs", fake_score_jobs)

    with client.stream(
        "GET",
        "/api/rank-opportunities",
        params=[
            ("likes", "hands-on work"),
            ("likes", "problem solving"),
            ("location", "Buffalo area"),
        ],
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: batch" in body
    assert "event: progress" in body
    assert "event: done" in body

    print(body)
    # Local Western NY opportunity can remain Strong.
    assert "Strong" in body
    assert "Boilermaker Apprentice" in body
    assert "Good local match for fixing mechanical equipment." in body

    # Binghamton/Southern Tier opportunity is capped from Strong to Moderate
    # for a Buffalo-area user.
    assert "Moderate" in body
    assert "Electrician Apprentice" in body
    assert "Good match for hands-on troubleshooting work." in body

    # Stream endpoint only returns ranked cards/progress, not the full page shell.
    assert "Sheet Metal Worker Apprentice" not in body


def test_ranked_opportunities_page_renders_streaming_shell_and_unranked_jobs(client):
    """Verifies that the ranked opportunities page renders the streaming shell
    and still includes non-O*NET jobs in the unranked section."""
    response = client.get(
        "/opportunities",
        params=[
            ("ranked", "true"),
            ("likes", "hands-on work"),
            ("likes", "problem solving"),
            ("location", "Buffalo area"),
        ],
    )

    assert response.status_code == 200

    # Ranked page shell.
    assert "Matched to your profile" in response.text
    assert "hands-on work" in response.text
    assert "problem solving" in response.text
    assert "Analyzing opportunities…" in response.text

    # The page should connect to the streaming ranking endpoint.
    assert "sse-connect" in response.text
    assert "/api/rank-opportunities" in response.text
    assert "likes=hands-on+work" in response.text
    assert "likes=problem+solving" in response.text

    # Non-O*NET opportunity still appears as unranked on the page shell.
    assert "More opportunities" in response.text
    assert "Sheet Metal Worker Apprentice" in response.text


def make_server_rank_job(location_summary: str) -> dict:
    """Builds a minimal job object for testing server-side ranking behavior
    without needing the full opportunity fixture shape."""
    return {
        "id": "nyc-electrician-fixture",
        "posting": {
            "jobTitle": "Electrician Apprentice",
            "sourceTitle": "NYC Electricians Fixture",
            "locationSummary": location_summary,
            "regions": [],
            "allRequirements": [],
        },
    }


def test_build_ranked_items_caps_far_strong_match_when_location_matching_enabled():
    """Verifies that _build_ranked_items applies the location cap when the user
    has a local search preference and the job is far away."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": True,
    }
    job = make_server_rank_job("New York City, NY area")
    scores = [
        {
            "id": "nyc-electrician-fixture",
            "tier": "Strong",
            "explanation": "Strong interest fit.",
        }
    ]

    ranked = server._build_ranked_items(
        batch_jobs=[job],
        scores=scores,
        job_index={job["id"]: 0},
        profile=profile,
    )

    assert ranked[0]["tier"] == "Moderate"
    assert ranked[0]["location_fit"] == "far"


def test_build_ranked_items_does_not_cap_far_match_when_location_matching_disabled():
    """Verifies that _build_ranked_items skips the location cap when the user is
    open to opportunities anywhere in New York."""
    profile = {
        "likes": ["hands-on work"],
        "location": "Buffalo area",
        "use_location_matching": False,
    }
    job = make_server_rank_job("New York City, NY area")
    scores = [
        {
            "id": "nyc-electrician-fixture",
            "tier": "Strong",
            "explanation": "Strong interest fit.",
        }
    ]

    ranked = server._build_ranked_items(
        batch_jobs=[job],
        scores=scores,
        job_index={job["id"]: 0},
        profile=profile,
    )

    assert ranked[0]["tier"] == "Strong"
    assert ranked[0]["location_fit"] is None
