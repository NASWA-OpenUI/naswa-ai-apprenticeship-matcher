# NASWA AI Apprenticeship Matcher

A prototype web application for exploring apprenticeship opportunities and matching users to relevant jobs based on a short guided conversation.

The app uses AWS Strands and Bedrock to collect a simple interest profile, then rank apprenticeship opportunities against those interests. It uses [AWS Strands](https://strandsagents.com/) to run a lightweight chat flow, collect a simple user interest profile, and rank apprenticeship opportunities against those interests.

## What the app does

* Runs a guided chat flow that asks for the user’s name and hobbies
* Extracts a simple profile with name, hobbies, interest themes, and confirmation status
* Lists apprenticeship opportunities at `/opportunities`
* Shows individual opportunity detail pages at `/opportunities/{slug}`
* Displays O*NET and OES enrichment data when available
* Ranks O*NET-backed opportunities as `Strong`, `Moderate`, or `Weak` matches
* Uses NYS Design System styles and app-specific CSS for the prototype UI

Session handling is currently lightweight and in-memory.

## Tech stack

* Python 3.14
* FastAPI
* Jinja2 templates
* HTMX and Server-Sent Events
* SQLite
* Strands Agents SDK
* AWS Bedrock
* NYS Design System
* `uv` for dependency management
* `pytest` for route tests

## Repository layout

```text
.
├── data/                 # Apprenticeship opportunity JSON files and generated SQLite DB
├── infra/                # AWS ECS Express Mode deployment notes and IAM policy files
├── static/               # App CSS, images, and favicon
├── templates/            # Jinja2 pages and partials
├── tests/                # Route tests and fixtures
├── db.py                 # Loads and queries opportunity data
├── server.py             # FastAPI app, routes, chat flow, and ranking logic
├── Dockerfile            # Container build for deployment
├── pyproject.toml        # Python dependencies
└── README.md
```

## Data loading

On startup, the app reads every `*.json` file in `data/` and loads it into:

```text
data/_opportunities.db
```

Each JSON file represents one apprenticeship opportunity. The app expects a top-level `id`, a `posting` object, and optional enrichment objects such as `oes` and `onet`.

To add or update opportunity data, add JSON files to `data/` and restart the server.

## Setup

Install dependencies:

```bash
uv sync
```

Configure AWS credentials and a Bedrock-supported region in your environment or local `.env` file.

Example `.env`:

```bash
AWS_DEFAULT_REGION=us-east-2

# Optional. Defaults shown here.
CHAT_MODEL_NAME=sonnet-4.6
SCORING_MODEL_NAME=sonnet-4.6
```

Supported local model names are currently:

```text
sonnet-4.6
nova-lite
nova-2-lite
```

Do not commit `.env` files or AWS credentials.

## Run the app

```bash
uv run uvicorn server:app --reload
```

Then open:

```text
http://localhost:8000
```

## Main routes

```text
/                         Guided chat flow
/health                   Health check
/chat/stream              Server-Sent Events stream for chat responses
/opportunities            All apprenticeship opportunities
/opportunities/{slug}     Detail page for one opportunity
/api/rank-opportunities   HTMX endpoint for ranked opportunity results
```

## Development notes

Current assumptions:

* Opportunity data is loaded from local JSON files.
* SQLite is regenerated from the JSON files on startup.
* Browser sessions are stored in memory.
* Ranking is performed with a single LLM call against opportunities that include O*NET data.
* Opportunities without O*NET data are still shown, but are not ranked by the AI matcher.
* Deployment notes live in `infra/README.md`.
