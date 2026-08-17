# Program data

This folder contains the registered apprenticeship program group JSON files used by the NASWA AI Registered Apprenticeship Finder.

Each `*.json` file represents one O*NET-SOC occupation group and contains all included registered apprenticeship programs that share that SOC code. Programs within each file are grouped by trade name.

These files are loaded into the generated SQLite database at startup:

```text
data/_database.db
````

The JSON files are generated outside this app by the NASWA Apprenticeship Crawler:

```text
https://github.com/NASWA-OpenUI/naswa-apprenticeship-crawler
```

The crawler processes New York State registered apprenticeship program data, groups programs by SOC code and trade name, enriches each SOC group with O*NET occupation data, adds generated plain-language trade names and descriptions, and writes the final JSON files to its `programs/out/` folder.

## Refreshing this data

1. Run the program processing steps documented in the crawler repo.
2. In this app repo, delete the existing JSON files in this folder:

```bash
rm data/programs/*.json
```

3. Copy the newly generated JSON files from the crawler repo’s `programs/out/` folder into this folder.
4. Rebuild the local SQLite database:

```bash
uv run python -c "from naswa_matcher.db import load; load(); print('loaded')"
```

5. Run the tests:

```bash
uv run pytest
```

Do not edit `data/_database.db` directly. It is generated from the source files in `data/opportunities/`, `data/programs/`, and `data/locations/`.
