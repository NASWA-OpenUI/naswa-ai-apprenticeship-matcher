# NASWA AI Apprenticeship Matcher

A prototype web application for exploring apprenticeship opportunities and matching users to relevant jobs based on a short guided conversation. This project is funded with support from the GitLab Foundation and built in partnership between the National Association of State Workforce Agencies and the New York State Department of Labor. This tool is currently running on a limited dataset and should not be used to make career or other life decisions. If you have questions or suggestions for improvement, please email [ajohnson@naswa.org](mailto:ajohnson@naswa.org) or [p.craig@bloomworks.digital](mailto:p.craig@bloomworks.digital).

The app uses AWS Strands and Bedrock to collect a simple user profile, then rank apprenticeship opportunities against that profile.

## What the app does

* Shows a landing page at `/`
* Runs a guided chat flow at `/chat` that asks about the user’s interests, location, and transportation
* Builds an editable profile with name, likes, dislikes, location, and transportation
* Lists apprenticeship opportunities at `/opportunities`
* Shows individual opportunity detail pages at `/opportunities/{slug}`
* Displays O*NET and OES enrichment data when available
* Streams ranked opportunities as `Strong`, `Moderate`, or `Weak` matches
* Filters ranked results by match strength, region, and driver’s licence requirement
* Uses NYS Design System styles and app-specific CSS for the prototype UI

Browser sessions and completed ranking results are stored in memory.

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
* `pytest` for automated tests
* `black` and `isort` for formatting

## Repository layout

```text
.
├── data/                 # Opportunity and location source data plus generated SQLite DB
├── infra/                # AWS ECS Express Mode deployment notes, policies, and scripts
├── naswa_logs/           # Local scripts for exporting and summarizing server logs
├── naswa_matcher/        # Application helpers, models, ranking, sessions, and logging
├── static/               # App CSS, images, and favicon
├── templates/            # Jinja2 pages and partials
├── tests/                # Automated tests and fixtures
├── server.py             # FastAPI app, routes, chat flow, and ranking orchestration
├── Dockerfile            # Container build for deployment
├── pyproject.toml        # Python dependencies and tool config
└── README.md
```

## Data loading

On startup, the app reads opportunity JSON files from:

```text
data/opportunities/
```

It also reads the location reference CSVs under `data/locations/`. The data is loaded into the generated database:

```text
data/_database.db
```

Each opportunity file expects a top-level `id`, a `posting` object, and optional enrichment objects such as `jobDescription`, `oes`, and `onet`.

To refresh the data, replace the source files and restart the server so the database is rebuilt.

## Setup

Install dependencies:

```bash
uv sync
```

Configure AWS credentials and a Bedrock-supported region in your environment or local `.env` file.

Example `.env`:

```bash
AWS_DEFAULT_REGION=us-east-1

# Optional. Defaults shown here.
CHAT_MODEL_NAME=sonnet-4.6
SCORING_MODEL_NAME=nova-2-lite
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
# Run the app normally
uv run uvicorn server:app --reload

# Run the app with DEBUG logs
NASWA_LOG_LEVEL=DEBUG uv run uvicorn server:app --reload
```

Then open:

```text
http://localhost:8000
```

## Main routes

```text
/                         Landing page
/ai-disclosure            AI disclosure page
/chat                     Guided chat and profile editing
/chat/stream              Server-Sent Events stream for chat responses
/opportunities            Opportunity listing and ranked results
/opportunities/{slug}     Detail page for one opportunity
/api/rank-opportunities   Server-Sent Events stream for opportunity ranking
/health                   Health check
```

## Development commands

Format Python files and sort imports:

```bash
uv run isort .
uv run black .
```

Check formatting without changing files:

```bash
uv run isort --check-only .
uv run black --check .
```

Run tests:

```bash
uv run pytest
```

### Accessibility testing

Application pages and important interaction states are also tested for accessibility using the [axe DevTools browser extension](https://chromewebstore.google.com/detail/axe-devtools-web-accessib/lhdoppojpmngadmnindnejefpokejbdd).

These browser-based scans complement the automated Python test suite and are used to identify issues involving page structure, accessible names, color contrast, form controls, keyboard interaction, and ARIA usage.

## Development notes

Current assumptions:

* Opportunity data is loaded from local JSON files.
* SQLite is regenerated from the JSON files on startup.
* Browser sessions are stored in memory.
* Ranking is streamed in batches against opportunities that include O*NET data.
* Opportunities without O*NET data are still shown, but are not ranked by the AI matcher.
* Deployment notes live in `infra/README.md`.
