# NASWA AI Apprenticeship Matcher

A prototype web application for exploring apprenticeship opportunities and matching users to relevant jobs based on a short guided conversation.

This app was derived from an AWS Strands Agents SDK tutorial and is now being developed as a NASWA apprenticeship finder prototype. It uses Strands to run a lightweight chat flow, collect a simple user interest profile, and rank apprenticeship opportunities against those interests.

## What the app does

The app currently supports:

- A guided chat flow at `/` that asks the user for their name and hobbies
- Simple profile extraction from the chat, including name, hobbies, and interest themes
- An apprenticeship opportunities list at `/opportunities`
- Individual opportunity detail pages at `/opportunities/{slug}`
- O\*NET and OES enrichment data, where available, for occupation descriptions, work activities, work styles, and wage information
- AI-assisted ranking of O\*NET-backed opportunities as `Strong`, `Moderate`, or `Weak` matches based on the user’s interests

This is still a prototype. The current session handling is lightweight and in-memory, and the app is intended for local development and demonstration.

## Tech stack

- Python
- FastAPI
- Jinja2 templates
- HTMX and Server-Sent Events
- SQLite
- Strands Agents SDK
- AWS Bedrock / Amazon Nova
- `uv` for dependency management

## Repository layout

```text
.
├── data/
│   ├── *.json                 # Apprenticeship opportunity source data
│   └── _opportunities.db      # Generated SQLite database
├── db.py                      # Loads and queries opportunity data
├── server.py                  # FastAPI app, routes, chat flow, and ranking logic
├── pyproject.toml             # Python project dependencies
├── templates/
│   ├── chat.html              # Guided chat page
│   ├── opportunities.html     # Opportunity list page
│   ├── opportunity.html       # Opportunity detail page
│   ├── _message.html          # Chat message partial
│   ├── _profile_card.html     # Confirmed user profile partial
│   └── _rank_results.html     # Ranked opportunity results partial
└── static/
```

## Data loading

On startup, the app reads every `*.json` file in `data/` and loads it into a local SQLite database at:

```text
data/_opportunities.db
```

Each JSON file represents one apprenticeship opportunity. The app expects records with a top-level `id`, a `posting` object, and optional enrichment objects such as `oes` and `onet`.

To add or update opportunity data, add JSON files to `data/` and restart the server.

## Setup

Install dependencies with `uv`:

```bash
uv sync
```

The app uses AWS Strands with the Amazon Nova model:

```text
us.amazon.nova-lite-v1:0
```

For chat and ranking features to work, configure AWS credentials and a Bedrock-supported region in your environment or in a local `.env` file.

Example `.env`:

```bash
AWS_DEFAULT_REGION=us-east-1
```

Do not commit `.env` files or AWS credentials.

## Run the app

Start the development server:

```bash
uv run uvicorn server:app --reload
```

Then open:

```text
http://localhost:8000
```

## Main pages

```text
/                         Guided chat flow
/opportunities            All apprenticeship opportunities
/opportunities/{slug}     Detail page for one opportunity
/api/rank-opportunities   HTMX endpoint for ranked opportunity results
```

## Development notes

This app is intentionally small and prototype-oriented.

Current assumptions:

- Opportunity data is loaded from local JSON files.
- SQLite is regenerated from the JSON files on startup.
- Browser sessions are stored in memory.
- Ranking is performed with a single LLM call against opportunities that include O\*NET data.
- Opportunities without O\*NET data are still shown, but are not ranked by the AI matcher.
