from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "_opportunities.db"
REFERENCE_DIR = DATA_DIR / "reference"

LABOR_MARKET_REGIONS_CSV = REFERENCE_DIR / "Labor_Market_Regions.csv"
LOCALITY_HIERARCHY_CSV = (
    REFERENCE_DIR / "New_York_State_Locality_Hierarchy_with_Websites.csv"
)
LOCATION_ALIASES_CSV = REFERENCE_DIR / "location_aliases.csv"


IGNORED_LOCATION_TERMS = {"new york", "york"}

REGION_NAME_TO_KEY = {
    "Capital Region": "capital",
    "Central New York": "central",
    "Finger Lakes": "finger_lakes",
    "Hudson Valley": "hudson_valley",
    "Long Island": "long_island",
    "Mohawk Valley": "mohawk_valley",
    "New York City": "new_york_city",
    "North Country": "north_country",
    "Southern Tier": "southern_tier",
    "Western New York": "western",
}

REGION_KEY_TO_NAME = {key: name for name, key in REGION_NAME_TO_KEY.items()}


@dataclass(frozen=True)
class LocationTerm:
    term: str
    region_keys: frozenset[str]


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _normalize(value: str | None) -> str:
    return " ".join(_clean(value).lower().split())


def _region_key(region_name: str) -> str:
    cleaned = _clean(region_name)

    try:
        return REGION_NAME_TO_KEY[cleaned]
    except KeyError as exc:
        raise ValueError(f"Unknown labor market region: {region_name!r}") from exc


def _require_csv(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing location reference CSV: {path}. "
            "See data/reference/README.md for download instructions."
        )


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS location_regions (
            region_key TEXT PRIMARY KEY,
            region_name TEXT NOT NULL UNIQUE
        )
        """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS location_counties (
            county_name TEXT PRIMARY KEY,
            county_name_norm TEXT NOT NULL UNIQUE,
            region_key TEXT NOT NULL
        )
        """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS location_localities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            locality_name TEXT NOT NULL,
            locality_name_norm TEXT NOT NULL,
            locality_type TEXT,
            county_name TEXT NOT NULL,
            region_key TEXT NOT NULL
        )
        """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS location_aliases (
            alias TEXT PRIMARY KEY,
            alias_norm TEXT NOT NULL UNIQUE,
            region_key TEXT NOT NULL
        )
        """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_location_localities_norm
        ON location_localities (locality_name_norm)
        """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_location_counties_norm
        ON location_counties (county_name_norm)
        """)


def _read_county_regions(path: Path) -> dict[str, str]:
    county_regions: dict[str, str] = {}

    with path.open(newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            county_name = _clean(row.get("County"))
            region_name = _clean(row.get("Region"))

            if not county_name or not region_name:
                continue

            county_regions[county_name] = _region_key(region_name)

    return county_regions


def _locality_names(row: dict[str, str]) -> set[str]:
    names = {
        _clean(row.get("Municipality")),
        _clean(row.get("City Name")),
        _clean(row.get("Town Name")),
        _clean(row.get("Village Name")),
    }

    return {name for name in names if name}


def load_location_data(
    conn: sqlite3.Connection,
    *,
    reference_dir: Path = REFERENCE_DIR,
) -> None:
    """
    Load static NY location reference CSVs into SQLite.

    This is called from db.load() on startup. The tables are rebuilt from the
    vendored CSV files each time the local app database is regenerated.
    """
    labor_market_regions_csv = reference_dir / LABOR_MARKET_REGIONS_CSV.name
    locality_hierarchy_csv = reference_dir / LOCALITY_HIERARCHY_CSV.name
    location_aliases_csv = reference_dir / LOCATION_ALIASES_CSV.name

    _require_csv(labor_market_regions_csv)
    _require_csv(locality_hierarchy_csv)

    _create_tables(conn)

    conn.execute("DELETE FROM location_aliases")
    conn.execute("DELETE FROM location_localities")
    conn.execute("DELETE FROM location_counties")
    conn.execute("DELETE FROM location_regions")

    for region_key, region_name in REGION_KEY_TO_NAME.items():
        conn.execute(
            """
            INSERT INTO location_regions (region_key, region_name)
            VALUES (?, ?)
            """,
            (region_key, region_name),
        )

    county_regions = _read_county_regions(labor_market_regions_csv)

    for county_name, region_key in sorted(county_regions.items()):
        conn.execute(
            """
            INSERT INTO location_counties (
                county_name,
                county_name_norm,
                region_key
            )
            VALUES (?, ?, ?)
            """,
            (county_name, _normalize(county_name), region_key),
        )

    with locality_hierarchy_csv.open(newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            county_names = [
                _clean(row.get("County Name")),
                _clean(row.get("2nd County")),
            ]

            for county_name in county_names:
                if not county_name:
                    continue

                region_key = county_regions.get(county_name)
                if not region_key:
                    continue

                for locality_name in _locality_names(row):
                    conn.execute(
                        """
                        INSERT INTO location_localities (
                            locality_name,
                            locality_name_norm,
                            locality_type,
                            county_name,
                            region_key
                        )
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            locality_name,
                            _normalize(locality_name),
                            _clean(row.get("Type")),
                            county_name,
                            region_key,
                        ),
                    )

    if location_aliases_csv.exists():
        with location_aliases_csv.open(newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                alias = _clean(row.get("Alias"))
                region = _clean(row.get("Region"))

                if not alias or not region:
                    continue

                conn.execute(
                    """
                    INSERT OR REPLACE INTO location_aliases (
                        alias,
                        alias_norm,
                        region_key
                    )
                    VALUES (?, ?, ?)
                    """,
                    (alias, _normalize(alias), _region_key(region)),
                )

    clear_location_terms_cache()


def _has_reference_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'location_regions'
        """).fetchone()

    return row is not None


def _merge_terms(rows: list[tuple[str, str]]) -> tuple[LocationTerm, ...]:
    merged: dict[str, set[str]] = {}

    for term, region_key in rows:
        normalized_term = _normalize(term)

        if not normalized_term:
            continue

        if normalized_term in IGNORED_LOCATION_TERMS:
            continue

        merged.setdefault(normalized_term, set()).add(region_key)

    return tuple(
        LocationTerm(term=term, region_keys=frozenset(region_keys))
        for term, region_keys in sorted(
            merged.items(),
            key=lambda item: (-len(item[0]), item[0]),
        )
    )


def _location_terms_from_db() -> tuple[LocationTerm, ...]:
    if not DB_PATH.exists():
        return tuple()

    conn = sqlite3.connect(DB_PATH)

    try:
        if not _has_reference_tables(conn):
            return tuple()

        rows = conn.execute("""
            SELECT region_name AS term, region_key FROM location_regions

            UNION ALL

            SELECT county_name AS term, region_key FROM location_counties

            UNION ALL

            SELECT county_name || ' county' AS term, region_key
            FROM location_counties

            UNION ALL

            SELECT locality_name AS term, region_key
            FROM location_localities
            WHERE locality_name_norm NOT IN (
                SELECT alias_norm FROM location_aliases
            )

            UNION ALL

            SELECT alias AS term, region_key FROM location_aliases
            """).fetchall()

        return _merge_terms([(row[0], row[1]) for row in rows])

    finally:
        conn.close()


def _location_terms_from_csv() -> tuple[LocationTerm, ...]:
    """
    Fallback for unit tests or scripts that call infer_location_groups() before
    db.load() has created SQLite reference tables.
    """
    if not LABOR_MARKET_REGIONS_CSV.exists() or not LOCALITY_HIERARCHY_CSV.exists():
        return tuple()

    rows: list[tuple[str, str]] = []

    alias_rows: list[tuple[str, str]] = []
    alias_norms: set[str] = set()

    if LOCATION_ALIASES_CSV.exists():
        with LOCATION_ALIASES_CSV.open(newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                alias = _clean(row.get("Alias"))
                region = _clean(row.get("Region"))

                if alias and region:
                    alias_rows.append((alias, _region_key(region)))
                    alias_norms.add(_normalize(alias))

    county_regions = _read_county_regions(LABOR_MARKET_REGIONS_CSV)

    for region_name, region_key in REGION_NAME_TO_KEY.items():
        rows.append((region_name, region_key))

    for county_name, region_key in county_regions.items():
        rows.append((county_name, region_key))
        rows.append((f"{county_name} County", region_key))

    with LOCALITY_HIERARCHY_CSV.open(newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            county_names = [
                _clean(row.get("County Name")),
                _clean(row.get("2nd County")),
            ]

            for county_name in county_names:
                if not county_name:
                    continue

                region_key = county_regions.get(county_name)
                if not region_key:
                    continue

                for locality_name in _locality_names(row):
                    if _normalize(locality_name) in alias_norms:
                        continue

                    rows.append((locality_name, region_key))

    rows.extend(alias_rows)

    return _merge_terms(rows)


@lru_cache(maxsize=1)
def location_terms() -> tuple[LocationTerm, ...]:
    """Return all known location terms mapped to official app region keys."""
    return _location_terms_from_db() or _location_terms_from_csv()


def clear_location_terms_cache() -> None:
    location_terms.cache_clear()
