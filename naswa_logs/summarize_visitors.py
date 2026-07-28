#!/usr/bin/env python3
"""Create one aggregate CSV row per visitor for a selected UTC date.

The script is intended to live in a ``naswa_logs`` directory alongside daily
CloudWatch exports named with this exact pattern:

    YYYY-MM-DD-logs.csv

Running without arguments processes today's UTC date. For example, on
2026-07-28 it requires:

    naswa_logs/2026-07-28-logs.csv

It writes the summary to:

    naswa_logs/2026-07-28/visitor-summary-2026-07-28.csv

The output directory is reused when it already exists, and the summary file is
overwritten on every run.

Journey rules
-------------
- Events are grouped by ``visitor_id`` and sorted by their UTC timestamp.
- A gap of 59 minutes or more starts a new journey.
- Only journeys whose first event occurred on the selected UTC date are included.
- The previous day's file is read when present only to identify journeys that
  started before the selected date and should therefore be excluded.
- The next day's file is read when present so qualifying journeys can be
  completed across midnight. No files beyond the next day are read.
- Multiple qualifying journeys for the same visitor are aggregated into one row.

Expected input
--------------
A CloudWatch CSV with a JSON log-object column such as ``message``, ``@message``,
or ``raw_json``. Timestamp columns commonly exported by CloudWatch are also
supported.

Examples
--------
Process today's UTC date:

    python naswa_logs/summarize_cloudwatch_visitors.py

Backfill another date:

    python naswa_logs/summarize_cloudwatch_visitors.py --date 2026-07-28

Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlsplit

MESSAGE_COLUMNS = ("message", "@message", "raw_json")
TIMESTAMP_COLUMNS = (
    "timestamp",
    "@timestamp",
    "cloudwatch_timestamp",
    "cloudwatch_timestamp_ms",
)

JOURNEY_INACTIVITY = timedelta(minutes=59)

SUMMARY_FIELDS = [
    "user",
    "visitor_id",
    "first_seen_utc",
    "last_seen_utc",
    "journeys",
    "session_minutes",
    "actions",
    "page_views",
    "user_messages",
    "assistant_messages",
    "profile_confirmed",
    "rankings_completed",
    "opportunities_viewed",
    "latest_likes",
    "latest_dislikes",
    "latest_location",
    "latest_transportation",
    "activity_timeline",
]


def clean_text(value: object) -> str:
    """Return single-line, spreadsheet-friendly text."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def first_present(row: dict[str, str], names: tuple[str, ...]) -> str:
    """Return the first non-empty value from possible CSV column names."""
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return ""


def parse_json_message(raw: str) -> dict | None:
    """Parse a JSON log object, tolerating literal control characters."""
    try:
        parsed = json.loads(raw, strict=False)
    except json.JSONDecodeError, TypeError:
        return None

    return parsed if isinstance(parsed, dict) else None


def parse_datetime(value: object) -> datetime | None:
    """Parse an ISO timestamp or Unix timestamp into a UTC datetime."""
    if value in (None, ""):
        return None

    text = str(value).strip()

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        pass

    try:
        numeric = float(text)
    except ValueError:
        return None

    # CloudWatch timestamps are commonly Unix milliseconds.
    if abs(numeric) >= 100_000_000_000:
        numeric /= 1000

    try:
        return datetime.fromtimestamp(numeric, tz=UTC)
    except OverflowError, OSError, ValueError:
        return None


def event_datetime(event: dict, cloudwatch_timestamp: str) -> datetime | None:
    """Prefer the application timestamp, falling back to CloudWatch time."""
    return parse_datetime(event.get("timestamp")) or parse_datetime(
        cloudwatch_timestamp
    )


def url_parts(url: str) -> tuple[str, dict[str, list[str]]]:
    parsed = urlsplit(url or "")
    return parsed.path, parse_qs(parsed.query, keep_blank_values=True)


def joined_query(query: dict[str, list[str]], key: str) -> str:
    return "; ".join(
        clean_text(unquote_plus(value)) for value in query.get(key, []) if value
    )


def profile_from_url(url: str) -> dict[str, str]:
    """Extract profile values embedded in ranked-page URLs."""
    _path, query = url_parts(url)
    return {
        "likes": joined_query(query, "likes"),
        "dislikes": joined_query(query, "dislikes"),
        "location": joined_query(query, "location"),
        "transportation": joined_query(query, "transportation"),
    }


def is_head_probe(event: dict) -> bool:
    """Identify HEAD / traffic from health checks or scanners."""
    return event.get("method") == "HEAD" and event.get("url") == "/"


def friendly_action(event: dict) -> str:
    """Translate technical log actions into colleague-friendly labels."""
    action = clean_text(event.get("action"))
    url = str(event.get("url") or "")
    path, _query = url_parts(url)

    known_actions = {
        "user_message_sent": "Sent chat message",
        "assistant_message_received": "Received chat response",
        "location_inferred": "Matched location to region",
        "profile_confirmed": "Completed profile",
        "edit_profile": "Edited profile",
        "keep_chatting": "Continued profile chat",
        "chat_reset": "Reset chat",
        "ranking_started": "AI ranking started",
        "ranking_completed": "AI ranking completed",
        "ranking_cache_hit": "Loaded cached ranking",
        "ranking_batch_failed": "Ranking batch failed",
        "chat_agent_failed": "Chat AI error",
    }

    if action in known_actions:
        return known_actions[action]

    if action == "pageview":
        if path == "/":
            return "Viewed home page"
        if path == "/chat":
            return "Opened matching chat"
        if path == "/opportunities":
            return (
                "Viewed personalized matches"
                if "ranked=true" in url
                else "Viewed opportunities"
            )
        if path.startswith("/opportunities/"):
            return "Viewed apprenticeship opportunity"
        if path == "/ai-disclosure":
            return "Viewed AI disclosure"
        return "Viewed page"

    if action:
        return action.replace("_", " ").title()

    if event.get("record_type") == "request":
        return "HTTP request"

    return "Log event"


def load_events(
    input_path: Path,
    *,
    include_head_probes: bool,
    file_order: int,
) -> tuple[list[dict], dict[str, int]]:
    """Load visitor-associated JSON events from one CloudWatch CSV."""
    events: list[dict] = []
    stats = {
        "source_rows": 0,
        "invalid_json": 0,
        "missing_timestamp": 0,
        "without_visitor_id": 0,
        "head_probes": 0,
    }

    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)

        if reader.fieldnames is None:
            raise ValueError(f"The input CSV has no header row: {input_path}")

        if not any(name in reader.fieldnames for name in MESSAGE_COLUMNS):
            expected = ", ".join(MESSAGE_COLUMNS)
            found = ", ".join(reader.fieldnames)
            raise ValueError(
                f"Could not find a JSON message column in {input_path.name}. "
                f"Expected one of: {expected}. Found: {found}"
            )

        for source_order, source_row in enumerate(reader, start=1):
            stats["source_rows"] += 1
            raw_message = first_present(source_row, MESSAGE_COLUMNS)
            event = parse_json_message(raw_message)

            if event is None:
                stats["invalid_json"] += 1
                continue

            visitor_id = clean_text(event.get("visitor_id"))
            if not visitor_id:
                stats["without_visitor_id"] += 1
                continue

            if is_head_probe(event) and not include_head_probes:
                stats["head_probes"] += 1
                continue

            cloudwatch_timestamp = first_present(source_row, TIMESTAMP_COLUMNS)
            timestamp = event_datetime(event, cloudwatch_timestamp)
            if timestamp is None:
                stats["missing_timestamp"] += 1
                continue

            event["visitor_id"] = visitor_id
            event["_dt"] = timestamp
            event["_source_sort"] = (file_order, source_order)
            event["_friendly_action"] = friendly_action(event)
            event["_profile"] = profile_from_url(str(event.get("url") or ""))
            events.append(event)

    events.sort(key=lambda event: (event["_dt"], event["_source_sort"]))
    return events, stats


def combine_stats(stats_items: list[dict[str, int]]) -> dict[str, int]:
    keys = {key for stats in stats_items for key in stats}
    return {
        key: sum(stats.get(key, 0) for stats in stats_items) for key in sorted(keys)
    }


def split_journeys(events: list[dict]) -> list[list[dict]]:
    """Split sorted events when inactivity reaches 59 minutes."""
    if not events:
        return []

    journeys: list[list[dict]] = [[events[0]]]

    for event in events[1:]:
        previous = journeys[-1][-1]
        if event["_dt"] - previous["_dt"] >= JOURNEY_INACTIVITY:
            journeys.append([event])
        else:
            journeys[-1].append(event)

    return journeys


def qualifying_journeys(
    events: list[dict],
    *,
    target_date: date,
) -> dict[str, list[list[dict]]]:
    """Return journeys that begin on the selected UTC date, grouped by visitor."""
    grouped_events: defaultdict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped_events[str(event["visitor_id"])].append(event)

    selected: dict[str, list[list[dict]]] = {}

    for visitor_id, visitor_events in grouped_events.items():
        visitor_events.sort(key=lambda event: (event["_dt"], event["_source_sort"]))
        journeys = split_journeys(visitor_events)
        matching = [
            journey for journey in journeys if journey[0]["_dt"].date() == target_date
        ]
        if matching:
            selected[visitor_id] = matching

    return selected


def assign_user_labels(
    grouped_journeys: dict[str, list[list[dict]]],
) -> dict[str, str]:
    """Label visitors User 1, User 2, etc. in first-seen order."""
    visitor_ids = sorted(
        grouped_journeys,
        key=lambda visitor_id: grouped_journeys[visitor_id][0][0]["_dt"],
    )
    return {
        visitor_id: f"User {number}"
        for number, visitor_id in enumerate(visitor_ids, start=1)
    }


def flatten_journeys(journeys: list[list[dict]]) -> list[dict]:
    return [event for journey in journeys for event in journey]


def count_opportunity_views(events: list[dict]) -> int:
    count = 0
    for event in events:
        if event.get("action") != "pageview":
            continue
        path, _query = url_parts(str(event.get("url") or ""))
        if path.startswith("/opportunities/"):
            count += 1
    return count


def latest_profile(events: list[dict]) -> dict[str, str]:
    latest = {
        "likes": "",
        "dislikes": "",
        "location": "",
        "transportation": "",
    }

    for event in events:
        for key, value in event["_profile"].items():
            if value:
                latest[key] = value

    return latest


def utc_datetime_text(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def journey_minutes(journey: list[dict]) -> float:
    if not journey:
        return 0.0
    return (journey[-1]["_dt"] - journey[0]["_dt"]).total_seconds() / 60


def timeline_text(journeys: list[list[dict]]) -> str:
    journey_texts = []

    for journey in journeys:
        journey_texts.append(
            " → ".join(
                f"{event['_dt'].astimezone(UTC).strftime('%Y-%m-%d %H:%M:%S')} "
                f"{event['_friendly_action']}"
                for event in journey
            )
        )

    # A double pipe makes separate journeys visible in one spreadsheet cell.
    return " || ".join(journey_texts)


def build_summary_rows(
    grouped_journeys: dict[str, list[list[dict]]],
) -> list[dict[str, object]]:
    labels = assign_user_labels(grouped_journeys)
    rows: list[dict[str, object]] = []

    for visitor_id in sorted(
        grouped_journeys,
        key=lambda value: grouped_journeys[value][0][0]["_dt"],
    ):
        journeys = grouped_journeys[visitor_id]
        events = flatten_journeys(journeys)
        first = events[0]["_dt"]
        last = events[-1]["_dt"]
        profile = latest_profile(events)

        rows.append(
            {
                "user": labels[visitor_id],
                "visitor_id": visitor_id,
                "first_seen_utc": utc_datetime_text(first),
                "last_seen_utc": utc_datetime_text(last),
                "journeys": len(journeys),
                "session_minutes": f"{sum(journey_minutes(j) for j in journeys):.1f}",
                "actions": len(events),
                "page_views": sum(
                    event.get("action") == "pageview" for event in events
                ),
                "user_messages": sum(
                    event.get("action") == "user_message_sent" for event in events
                ),
                "assistant_messages": sum(
                    event.get("action") == "assistant_message_received"
                    for event in events
                ),
                "profile_confirmed": yes_no(
                    any(event.get("action") == "profile_confirmed" for event in events)
                ),
                "rankings_completed": sum(
                    event.get("action") == "ranking_completed" for event in events
                ),
                "opportunities_viewed": count_opportunity_views(events),
                "latest_likes": profile["likes"],
                "latest_dislikes": profile["dislikes"],
                "latest_location": profile["location"],
                "latest_transportation": profile["transportation"],
                "activity_timeline": timeline_text(journeys),
            }
        )

    return rows


def write_summary(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Opening with "w" deliberately overwrites an earlier same-day summary.
    # UTF-8 with BOM opens cleanly in Excel and Google Sheets.
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize daily structured CloudWatch logs into one CSV row per "
            "visitor whose journey began on the selected UTC date."
        )
    )
    parser.add_argument(
        "--date",
        type=parse_iso_date,
        default=None,
        help="UTC date to process in YYYY-MM-DD format. Defaults to today in UTC.",
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing YYYY-MM-DD-logs.csv files. Defaults to the "
            "directory containing this script."
        ),
    )
    parser.add_argument(
        "--include-head-probes",
        action="store_true",
        help="Include HEAD / requests excluded as probe noise by default.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    target_date = args.date or datetime.now(UTC).date()
    logs_dir = (
        args.logs_dir.expanduser().resolve()
        if args.logs_dir is not None
        else Path(__file__).resolve().parent
    )

    current_path = logs_dir / f"{target_date.isoformat()}-logs.csv"
    previous_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)
    previous_path = logs_dir / f"{previous_date.isoformat()}-logs.csv"
    next_path = logs_dir / f"{next_date.isoformat()}-logs.csv"

    if not current_path.is_file():
        raise SystemExit(
            "Required daily log file not found.\n"
            f"Expected: {current_path}\n"
            f"Add a CloudWatch export named exactly "
            f"'{target_date.isoformat()}-logs.csv' and run the script again."
        )

    input_paths: list[tuple[str, Path]] = []
    if previous_path.is_file():
        input_paths.append(("previous-day boundary context", previous_path))
    input_paths.append(("selected date", current_path))
    if next_path.is_file():
        input_paths.append(("next-day journey continuation", next_path))

    all_events: list[dict] = []
    all_stats: list[dict[str, int]] = []

    try:
        for file_order, (_purpose, path) in enumerate(input_paths):
            events, stats = load_events(
                path,
                include_head_probes=args.include_head_probes,
                file_order=file_order,
            )
            all_events.extend(events)
            all_stats.append(stats)

        all_events.sort(key=lambda event: (event["_dt"], event["_source_sort"]))
        selected = qualifying_journeys(all_events, target_date=target_date)
        summary_rows = build_summary_rows(selected)

        output_dir = logs_dir / target_date.isoformat()
        output_path = output_dir / f"visitor-summary-{target_date.isoformat()}.csv"
        write_summary(output_path, summary_rows)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not summarize logs: {exc}") from exc

    stats = combine_stats(all_stats)
    included_journeys = sum(len(journeys) for journeys in selected.values())
    included_events = sum(
        len(journey) for journeys in selected.values() for journey in journeys
    )

    print(f"Target UTC date: {target_date.isoformat()}")
    for purpose, path in input_paths:
        print(f"Read ({purpose}): {path.name}")
    if not previous_path.is_file():
        print(
            "Previous-day file not present; carry-in journey detection is "
            "limited to the available data."
        )
    if not next_path.is_file():
        print("Next-day file not present; no cross-midnight continuation was added.")
    print(f"Source rows read: {stats.get('source_rows', 0)}")
    print(f"Visitors summarized: {len(summary_rows)}")
    print(f"Qualifying journeys: {included_journeys}")
    print(f"Visitor events included: {included_events}")
    print("Rows skipped without visitor_id: " f"{stats.get('without_visitor_id', 0)}")
    print(f"Invalid JSON rows skipped: {stats.get('invalid_json', 0)}")
    print(
        "Rows skipped without a usable timestamp: "
        f"{stats.get('missing_timestamp', 0)}"
    )
    print(f"HEAD / probes skipped: {stats.get('head_probes', 0)}")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
