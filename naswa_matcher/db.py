import json
import sqlite3
from pathlib import Path

from naswa_matcher.location_data import load_location_data

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "_opportunities.db"


def load() -> None:
    """Load local app data into SQLite, replacing existing generated rows."""
    conn = sqlite3.connect(DB_PATH)

    try:
        load_opportunities(conn)
        load_location_data(conn)
        conn.commit()
    finally:
        conn.close()


def load_opportunities(conn: sqlite3.Connection) -> None:
    """Read every opportunity JSON file in data/ into SQLite."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS opportunities "
        "(id TEXT PRIMARY KEY, data TEXT NOT NULL)"
    )
    conn.execute("DELETE FROM opportunities")

    for path in sorted(DATA_DIR.glob("*.json")):
        with path.open() as f:
            raw = json.load(f)

        conn.execute(
            "INSERT INTO opportunities (id, data) VALUES (?, ?)",
            (raw["id"], json.dumps(raw)),
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
