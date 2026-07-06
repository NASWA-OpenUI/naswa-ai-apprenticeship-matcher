# Opportunity data

This folder contains the merged apprenticeship opportunity JSON files used by the NASWA AI Apprenticeship Matcher.

Each `*.json` file represents one apprenticeship opportunity. These files are loaded into the generated SQLite database at startup:

```text
data/_database.db
```

The JSON files are generated outside this app by the NASWA Apprenticeship Crawler:

```text
https://github.com/NASWA-OpenUI/naswa-apprenticeship-crawler
```

That crawler fetches NY DOL apprenticeship announcements, converts them to Markdown, extracts structured posting data, enriches the postings with SOC, O*NET, OES wage data, and generated plain-language job descriptions, then writes merged JSON files to its `out/` folder.

## Refreshing this data

1. Run the crawler and processing steps documented in the crawler repo.
2. In this app repo, delete the existing JSON files in this folder:

```bash
rm data/opportunities/*.json
```

3. Copy the newly generated merged JSON files from the crawler repo’s `out/` folder into this folder.
4. Rebuild the local SQLite database:

```bash
uv run python -c "from naswa_matcher.db import load; load(); print('loaded')"
```

5. Run the tests:

```bash
uv run pytest
```

Do not edit `data/_database.db` directly. It is generated from the source files in `data/opportunities/` and `data/locations/`.
