#!/usr/bin/env python3
"""Create one detailed activity CSV per visitor for a selected UTC date.

This companion script is intended to live beside
``summarize_visitors.py`` in the ``naswa_logs`` directory.
Daily CloudWatch exports must use this exact filename pattern:

    YYYY-MM-DD-logs.csv

Running without arguments processes today's UTC date. For example, processing
2026-07-28 requires:

    naswa_logs/2026-07-28-logs.csv

It writes one file per qualifying visitor to the date's output directory:

    naswa_logs/2026-07-28/
        visitor-<visitor_id>-2026-07-28.csv

Journey selection is delegated to ``summarize_visitors.py`` so both
scripts use exactly the same rules:

- Events are grouped by ``visitor_id`` and sorted by UTC timestamp.
- A gap of 59 minutes or more starts a new journey.
- Only journeys whose first event occurred on the selected UTC date are included.
- The previous day's file is used when present only as carry-in boundary context.
- The next day's file is used when present to complete a journey across midnight.
- No files beyond the next day are read.
- HEAD / probe traffic is excluded by default.

If one visitor has multiple qualifying journeys on the selected date, all of
those journeys are written to that visitor's single activity file, in time order.
Event numbering starts at 1 within each visitor file.

Examples
--------
Process today's UTC date:

    python naswa_logs/export_visitor_activity.py

Backfill another date:

    python naswa_logs/export_visitor_activity.py --date 2026-07-28

Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from summarize_visitors import (
    assign_user_labels,
    clean_text,
    combine_stats,
    flatten_journeys,
    load_events,
    parse_iso_date,
    qualifying_journeys,
    url_parts,
    yes_no,
)

NEW_YORK_TZ = ZoneInfo("America/New_York")

ACTIVITY_FIELDS = [
    "user",
    "visitor_id",
    "event_number",
    "time_new_york",
    "time_utc",
    "action",
    "details",
    "page_or_endpoint",
    "likes",
    "dislikes",
    "location",
    "transportation",
    "status_code",
    "duration_ms",
    "model",
    "request_id",
    "technical_action",
]


def friendly_details(event: dict) -> str:
    """Return readable context for one structured log event."""
    action = clean_text(event.get("action"))
    url = str(event.get("url") or "")
    path, _query = url_parts(url)

    if action in {"user_message_sent", "assistant_message_received"}:
        return clean_text(event.get("message"))

    if action == "location_inferred":
        groups_value = event.get("groups") or []
        matches_value = event.get("matches") or []

        if isinstance(groups_value, list):
            groups = ", ".join(clean_text(value) for value in groups_value if value)
        else:
            groups = clean_text(groups_value)

        if isinstance(matches_value, list):
            matches = ", ".join(clean_text(value) for value in matches_value if value)
        else:
            matches = clean_text(matches_value)

        return " | ".join(value for value in (groups, matches) if value)

    fixed_details = {
        "profile_confirmed": "Profile was confirmed and ready for matching",
        "edit_profile": "Saved changes to the matching profile",
        "keep_chatting": "Returned to chat to revise the profile",
        "chat_reset": "Started the chat and profile flow over",
        "ranking_cache_hit": (
            "Reused a ranking already completed in this browser session"
        ),
    }
    if action in fixed_details:
        return fixed_details[action]

    if action == "ranking_started":
        jobs = event.get("jobs")
        if jobs not in (None, ""):
            return f"Started ranking {jobs} opportunities"
        return "Started AI ranking"

    if action == "ranking_completed":
        parts: list[str] = []
        completed = event.get("completed_jobs")
        jobs = event.get("jobs")
        elapsed_ms = event.get("elapsed_ms")

        if completed not in (None, "") or jobs not in (None, ""):
            completed_text = 0 if completed in (None, "") else completed
            jobs_text = 0 if jobs in (None, "") else jobs
            parts.append(f"{completed_text}/{jobs_text} opportunities ranked")

        if elapsed_ms not in (None, ""):
            try:
                parts.append(f"{float(elapsed_ms) / 1000:.1f} seconds")
            except (TypeError, ValueError):
                parts.append(f"{clean_text(elapsed_ms)} ms")

        if "cached" in event:
            parts.append(f"cached: {yes_no(bool(event.get('cached'))).lower()}")

        if "had_batch_error" in event:
            parts.append(
                "batch error: "
                f"{yes_no(bool(event.get('had_batch_error'))).lower()}"
            )

        return " | ".join(parts)

    if action in {"ranking_batch_failed", "chat_agent_failed"}:
        return clean_text(event.get("error"))

    if action == "pageview":
        if path.startswith("/opportunities/"):
            return path.removeprefix("/opportunities/")
        if path not in {"", "/", "/chat", "/opportunities", "/ai-disclosure"}:
            return path
        return ""

    if event.get("record_type") == "request":
        method = clean_text(event.get("method"))
        status = event.get("status_code")
        details = f"{method} {path}".strip()
        if status not in (None, ""):
            details += f" → HTTP {status}"
        return details

    return clean_text(event.get("message"))


def new_york_time_text(value: datetime) -> str:
    """Format a timestamp in New York local time for spreadsheet display."""
    return value.astimezone(NEW_YORK_TZ).strftime("%Y-%m-%d %I:%M:%S %p")


def utc_time_text(value: datetime) -> str:
    """Format a timestamp as an unambiguous UTC value."""
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_visitor_id(visitor_id: str) -> str:
    """Return a filename-safe representation of a visitor ID."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", visitor_id).strip("-.")
    return safe or "unknown"


def activity_rows(
    *,
    visitor_id: str,
    user_label: str,
    journeys: list[list[dict]],
) -> list[dict[str, object]]:
    """Build detailed CSV rows for one visitor's qualifying journeys."""
    events = flatten_journeys(journeys)
    events.sort(key=lambda event: (event["_dt"], event["_source_sort"]))

    rows: list[dict[str, object]] = []
    for event_number, event in enumerate(events, start=1):
        profile = event.get("_profile") or {}

        rows.append(
            {
                "user": user_label,
                "visitor_id": visitor_id,
                "event_number": event_number,
                "time_new_york": new_york_time_text(event["_dt"]),
                "time_utc": utc_time_text(event["_dt"]),
                "action": event.get("_friendly_action", ""),
                "details": friendly_details(event),
                "page_or_endpoint": clean_text(event.get("url")),
                "likes": clean_text(profile.get("likes")),
                "dislikes": clean_text(profile.get("dislikes")),
                "location": clean_text(profile.get("location")),
                "transportation": clean_text(profile.get("transportation")),
                "status_code": event.get("status_code", ""),
                "duration_ms": event.get("duration_ms", ""),
                "model": clean_text(event.get("model")),
                "request_id": clean_text(event.get("request_id")),
                "technical_action": clean_text(event.get("action")),
            }
        )

    return rows


def write_activity_file(
    output_path: Path,
    rows: list[dict[str, object]],
) -> None:
    """Write one visitor's activity, overwriting an existing same-day file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # UTF-8 with BOM opens cleanly in Excel and Google Sheets.
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTIVITY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def remove_stale_activity_files(output_dir: Path, target_date: date) -> int:
    """Remove earlier generated visitor files so reruns reflect current input."""
    removed = 0
    pattern = f"visitor-*-{target_date.isoformat()}.csv"

    for path in output_dir.glob(pattern):
        # The aggregate file is named visitor-summary-YYYY-MM-DD.csv and also
        # matches the broad glob above. It belongs to the companion script and
        # must never be removed here.
        if path.name == f"visitor-summary-{target_date.isoformat()}.csv":
            continue
        if path.is_file():
            path.unlink()
            removed += 1

    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create one detailed activity CSV per visitor whose journey began "
            "on the selected UTC date."
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
            "Directory containing YYYY-MM-DD-logs.csv files and "
            "summarize_visitors.py. Defaults to the directory "
            "containing this script."
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
            "Add a CloudWatch export named exactly "
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
        user_labels = assign_user_labels(selected)

        output_dir = logs_dir / target_date.isoformat()
        output_dir.mkdir(parents=True, exist_ok=True)
        stale_removed = remove_stale_activity_files(output_dir, target_date)

        output_paths: list[Path] = []
        included_events = 0

        ordered_visitors = sorted(
            selected,
            key=lambda visitor_id: selected[visitor_id][0][0]["_dt"],
        )

        for visitor_id in ordered_visitors:
            rows = activity_rows(
                visitor_id=visitor_id,
                user_label=user_labels[visitor_id],
                journeys=selected[visitor_id],
            )
            included_events += len(rows)

            output_path = output_dir / (
                f"visitor-{safe_visitor_id(visitor_id)}-"
                f"{target_date.isoformat()}.csv"
            )
            write_activity_file(output_path, rows)
            output_paths.append(output_path)

    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not export visitor activity: {exc}") from exc

    stats = combine_stats(all_stats)
    included_journeys = sum(len(journeys) for journeys in selected.values())

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
    print(f"Visitors exported: {len(output_paths)}")
    print(f"Qualifying journeys: {included_journeys}")
    print(f"Visitor events included: {included_events}")
    print(f"Earlier generated visitor files removed: {stale_removed}")
    print(
        "Rows skipped without visitor_id: "
        f"{stats.get('without_visitor_id', 0)}"
    )
    print(f"Invalid JSON rows skipped: {stats.get('invalid_json', 0)}")
    print(
        "Rows skipped without a usable timestamp: "
        f"{stats.get('missing_timestamp', 0)}"
    )
    print(f"HEAD / probes skipped: {stats.get('head_probes', 0)}")

    if output_paths:
        for output_path in output_paths:
            print(f"Wrote: {output_path}")
    else:
        print(f"No qualifying visitor journeys found for {target_date.isoformat()}.")


if __name__ == "__main__":
    main()
