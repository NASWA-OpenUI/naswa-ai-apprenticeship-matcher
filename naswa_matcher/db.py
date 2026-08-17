import json
import sqlite3
from pathlib import Path

from naswa_matcher.location_data import load_location_data

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
OPPORTUNITIES_DIR = DATA_DIR / "opportunities"
PROGRAMS_DIR = DATA_DIR / "programs"
DB_PATH = DATA_DIR / "_database.db"


def load() -> None:
    """Load local app data into SQLite, replacing existing generated rows."""
    conn = sqlite3.connect(DB_PATH)

    try:
        load_opportunities(conn)
        load_programs(conn)
        load_location_data(conn)
        conn.commit()
    finally:
        conn.close()


def load_opportunities(conn: sqlite3.Connection) -> None:
    """Read every opportunity JSON file in data/opportunities/ into SQLite."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS opportunities "
        "(id TEXT PRIMARY KEY, data TEXT NOT NULL)"
    )
    conn.execute("DELETE FROM opportunities")

    for path in sorted(OPPORTUNITIES_DIR.glob("*.json")):
        with path.open() as f:
            raw = json.load(f)

        conn.execute(
            "INSERT INTO opportunities (id, data) VALUES (?, ?)",
            (raw["id"], json.dumps(raw)),
        )


def load_programs(conn: sqlite3.Connection) -> None:
    """Read every program group JSON file in data/programs/ into SQLite."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS programs "
        "(soc_code TEXT PRIMARY KEY, data TEXT NOT NULL)"
    )
    conn.execute("DELETE FROM programs")

    for path in sorted(PROGRAMS_DIR.glob("*.json")):
        with path.open() as f:
            raw = json.load(f)

        conn.execute(
            "INSERT INTO programs (soc_code, data) VALUES (?, ?)",
            (raw["socCode"], json.dumps(raw)),
        )


def all_opportunities() -> list[dict]:
    """Return all opportunities sorted by recruitment end date ascending."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            "SELECT data FROM opportunities "
            "ORDER BY json_extract(data, '$.posting.applicationEndDate') ASC"
        ).fetchall()
        return [json.loads(r["data"]) for r in rows]
    finally:
        conn.close()


def get_opportunity(slug: str) -> dict | None:
    """Return a single opportunity by id, or None if not found."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        row = conn.execute(
            "SELECT data FROM opportunities WHERE id = ?", (slug,)
        ).fetchone()
        return json.loads(row["data"]) if row else None
    finally:
        conn.close()


def all_program_groups() -> list[dict]:
    """Return all registered apprenticeship program groups sorted by SOC code."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            "SELECT data FROM programs ORDER BY soc_code ASC"
        ).fetchall()
        return [json.loads(r["data"]) for r in rows]
    finally:
        conn.close()


def get_program_group(soc_code: str) -> dict | None:
    """Return a single registered apprenticeship program group by SOC code."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        row = conn.execute(
            "SELECT data FROM programs WHERE soc_code = ?", (soc_code,)
        ).fetchone()
        return json.loads(row["data"]) if row else None
    finally:
        conn.close()