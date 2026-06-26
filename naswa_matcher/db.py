import json
import sqlite3
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent

DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "_opportunities.db"


def load() -> None:
    """Read every *.json file in data/ into SQLite, replacing any existing rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS opportunities "
        "(id TEXT PRIMARY KEY, data TEXT NOT NULL)"
    )
    for path in sorted(DATA_DIR.glob("*.json")):
        with path.open() as f:
            raw = json.load(f)
        conn.execute(
            "INSERT OR REPLACE INTO opportunities (id, data) VALUES (?, ?)",
            (raw["id"], json.dumps(raw)),
        )
    conn.commit()
    conn.close()


def all_opportunities() -> list[dict]:
    """Return all opportunities sorted by recruitment end date ascending."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT data FROM opportunities "
        "ORDER BY json_extract(data, '$.posting.applicationEndDate') ASC"
    ).fetchall()
    conn.close()
    return [json.loads(r["data"]) for r in rows]


def get_opportunity(slug: str) -> dict | None:
    """Return a single opportunity by id, or None if not found."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT data FROM opportunities WHERE id = ?", (slug,)
    ).fetchone()
    conn.close()
    return json.loads(row["data"]) if row else None
