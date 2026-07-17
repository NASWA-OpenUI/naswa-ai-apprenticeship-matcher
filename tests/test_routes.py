import pytest

import server
from naswa_matcher.ranking import build_ranked_items


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


def test_page_includes_github_sha_when_configured(client, monkeypatch):
    """The shared page head exposes the deployed commit when configured."""
    github_sha = "12337f07bd6a1213015b1e2ea3673bc1dee223ed"
    monkeypatch.setenv("GITHUB_SHA", github_sha)

    response = client.get("/")

    assert response.status_code == 200
    assert f'<meta name="github-sha" content="{github_sha}">' in response.text


def test_page_omits_github_sha_when_not_configured(client, monkeypatch):
    """Local pages do not emit an empty deployment metadata tag."""
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    response = client.get("/")

    assert response.status_code == 200
    assert 'meta name="github-sha"' not in response.text


def test_ai_disclosure_route_renders_ai_disclosure_page(client):
    """Verifies that the AI disclosure page renders key disclosure sections,
    privacy/session language, and the call-to-action back into the chat flow."""
    response = client.get("/ai-disclosure")

    assert response.status_code == 200
    assert "AI Disclosure" in response.text
    assert "How this tool works, what info we ask you" in response.text


def test_chat_get_route_renders_chat_page(client):
    """Verifies that the chat page renders the initial assistant message,
    chat form, and SSE connection for streaming responses."""
    response = client.get("/chat")

    assert response.status_code == 200
    assert "To start, what’s your first name?" in response.text
    assert "Here’s the profile I’ll use to suggest matches" not in response.text
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


@pytest.mark.parametrize("message", ["", " ", "   ", "\t\n"])
def test_chat_route_ignores_blank_messages(client, message):
    """Blank messages should return successfully without changing the chat."""
    client.get("/chat")

    response = client.post("/chat", data={"message": message})

    assert response.status_code == 204
    assert response.content == b""

    page = client.get("/chat")

    assert "message--user" not in page.text


def test_chat_route_ignores_missing_message(client):
    """A missing message field should not produce a validation error."""
    response = client.post("/chat", data={})

    assert response.status_code == 204
    assert response.content == b""


def test_chat_get_route_prefills_confirmed_profile_from_query(client):
    """Verifies that /chat can accept profile query params and render the
    confirmed profile card immediately, without completing the AI chat flow."""
    response = client.get(
        "/chat",
        params=[
            ("likes", "art"),
            ("likes", "fashion"),
            ("dislikes", "office work"),
            ("location", "Buffalo"),
            ("transportation", "drives self"),
        ],
    )

    assert response.status_code == 200

    # The page should show the prefilled-profile state, not the initial chat prompt.
    assert "Here’s the profile I’ll use to suggest matches" in response.text
    assert "To start, what’s your first name?" not in response.text

    # Confirmed profile card.
    assert "Your Profile" in response.text
    assert "data-profile-card" in response.text
    assert "data-profile-json" in response.text
    assert "data-profile-edit-open" in response.text

    # Profile values.
    assert "art" in response.text
    assert "fashion" in response.text
    assert "office work" in response.text
    assert "Buffalo" in response.text
    assert "drives self" in response.text

    # The chat composer should be in the completed state.
    assert "Conversation complete" in response.text
    assert "disabled" in response.text

    # Modal partial should be available for editing.
    assert "data-profile-edit-modal" in response.text
    assert 'role="dialog"' in response.text
    assert 'aria-modal="true"' in response.text
    assert "data-profile-save" in response.text
    assert 'data-edit-list="likes"' in response.text
    assert 'data-edit-list="dislikes"' in response.text

    # Ranked URL should be built from the prefilled profile.
    assert "/opportunities?ranked=true" in response.text
    assert "likes=art" in response.text
    assert "likes=fashion" in response.text
    assert "dislikes=office+work" in response.text
    assert "location=Buffalo" in response.text
    assert "transportation=drives+self" in response.text


def test_chat_get_route_prefilled_profile_preserves_location_matching_false(client):
    """Verifies that a prefilled chat profile can opt out of location-based
    ranking and carries that preference into the ranked opportunities link."""
    response = client.get(
        "/chat",
        params=[
            ("likes", "art"),
            ("location", "Buffalo"),
            ("transportation", "drives self"),
            ("use_location_matching", "false"),
        ],
    )

    assert response.status_code == 200

    assert "Your Profile" in response.text
    assert "art" in response.text
    assert "Buffalo" in response.text
    assert "drives self" in response.text

    # The JSON profile used by the client-side editor should preserve this too.
    assert '"use_location_matching": false' in response.text

    # The ranked URL should also preserve the false value.
    assert "use_location_matching=false" in response.text


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
    assert "Starting wage" in response.text
    assert "$49,249" in response.text
    assert "Western New York" in response.text

    # O*NET enrichment.
    assert "About this job" in response.text
    assert "Install electrical components" in response.text
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


def test_ranked_opportunities_page_renders_streaming_shell_and_unranked_jobs(client):
    """Verifies that the ranked opportunities page renders the streaming shell,
    profile summary widget, and non-O*NET jobs in the unranked section."""
    response = client.get(
        "/opportunities",
        params=[
            ("ranked", "true"),
            ("likes", "hands-on work"),
            ("likes", "problem solving"),
            ("dislikes", "desk work"),
            ("location", "Buffalo area"),
        ],
    )

    assert response.status_code == 200

    assert "Matched to your profile" in response.text
    assert "hands-on work" in response.text
    assert "problem solving" in response.text
    assert "desk work" in response.text
    assert "Buffalo area" in response.text

    assert "Back to conversation" in response.text
    assert "Edit profile" in response.text
    assert "data-profile-summary" in response.text
    assert "data-profile-edit-modal" in response.text
    assert 'data-profile-save-mode="redirect"' in response.text

    assert "sse-connect" in response.text
    assert "/api/rank-opportunities" in response.text
    assert "likes=hands-on+work" in response.text
    assert "likes=problem+solving" in response.text
    assert "dislikes=desk+work" in response.text

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

    ranked = build_ranked_items(
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

    ranked = build_ranked_items(
        batch_jobs=[job],
        scores=scores,
        job_index={job["id"]: 0},
        profile=profile,
    )

    assert ranked[0]["tier"] == "Strong"
    assert ranked[0]["location_fit"] is None
