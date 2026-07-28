#!/usr/bin/env python3
"""Create one readable chronological CSV containing every log row for a UTC date.

This script is intended to live in the ``naswa_logs`` directory beside:

    summarize_visitors.py
    export_visitors.py

Daily CloudWatch exports must use this exact filename pattern:

    YYYY-MM-DD-logs.csv

Running without arguments processes today's UTC date. For example, processing
2026-07-28 requires:

    naswa_logs/2026-07-28-logs.csv

It writes, and overwrites when rerun:

    naswa_logs/2026-07-28/all-logs-2026-07-28.csv

Unlike the visitor summary and per-visitor activity scripts, this script:

- Reads only the selected date's file.
- Does not read the previous or next day's file.
- Does not split or stitch user journeys.
- Does not group rows by visitor.
- Preserves every source row, including application logs, probe traffic,
  records without a visitor ID, and unparsed log lines.
- Sorts rows chronologically using the application timestamp when available,
  then the CloudWatch timestamp, with source-row order as the tie-breaker.

Examples
--------
Process today's UTC date:

    python naswa_logs/all_logs.py

Backfill another date:

    python naswa_logs/all_logs.py --date 2026-07-28

Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, date, datetime
from pathlib import Path

from export_visitors import (
    friendly_details,
    new_york_time_text,
    utc_time_text,
)
from summarize_visitors import (
    MESSAGE_COLUMNS,
    TIMESTAMP_COLUMNS,
    clean_text,
    event_datetime,
    first_present,
    friendly_action,
    is_head_probe,
    parse_datetime,
    parse_iso_date,
    parse_json_message,
    yes_no,
)

ALL_LOG_FIELDS = [
    "source_row",
    "parsed_json",
    "user",
    "visitor_id",
    "probe_or_noise",
    "time_new_york",
    "time_utc",
    "level",
    "record_type",
    "action",
    "friendly_action",
    "details",
    "method",
    "url",
    "status_code",
    "request_id",
    "raw_message",
]


def probe_or_noise(event: dict | None) -> bool:
    """Return whether a row is operational noise rather than user activity."""
    if event is None:
        return True

    if is_head_probe(event):
        return True

    if not clean_text(event.get("visitor_id")):
        return True

    if event.get("record_type") == "application":
        return True

    return False


def readable_action(event: dict | None) -> str:
    """Return the friendly action label used in the all-events export."""
    if event is None:
        return "Unparsed log line"

    if event.get("record_type") == "application":
        return "Application log"

    if event.get("record_type") == "request" and event.get("action") == "request":
        return "HTTP request"

    return friendly_action(event)


def readable_details(event: dict | None, raw_message: str) -> str:
    """Return readable context while preserving unparsed lines."""
    if event is None:
        return clean_text(raw_message)

    return friendly_details(event)


def load_all_rows(input_path: Path) -> list[dict]:
    """Read every CloudWatch CSV row and attach parsed/sort metadata."""
    rows: list[dict] = []

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

        # source_row starts at 2 because row 1 is the CSV header.
        for source_row_number, source_row in enumerate(reader, start=2):
            raw_message = first_present(source_row, MESSAGE_COLUMNS)
            cloudwatch_timestamp = first_present(source_row, TIMESTAMP_COLUMNS)
            event = parse_json_message(raw_message)

            if event is not None:
                timestamp = event_datetime(event, cloudwatch_timestamp)
            else:
                timestamp = parse_datetime(cloudwatch_timestamp)

            visitor_id = (
                clean_text(event.get("visitor_id")) if event is not None else ""
            )

            rows.append(
                {
                    "_dt": timestamp,
                    "_source_row": source_row_number,
                    "_event": event,
                    "_raw_message": raw_message,
                    "_visitor_id": visitor_id,
                    "_probe_or_noise": probe_or_noise(event),
                }
            )

    # Timestamped rows come first chronologically. Rows with no usable timestamp
    # remain visible at the end in their original source order.
    rows.sort(
        key=lambda row: (
            row["_dt"] is None,
            row["_dt"] or datetime.max.replace(tzinfo=UTC),
            row["_source_row"],
        )
    )
    return rows


def assign_user_labels(rows: list[dict]) -> dict[str, str]:
    """Label meaningful visitors User 1, User 2, etc. by first activity."""
    first_activity: dict[str, tuple[datetime | None, int]] = {}

    for row in rows:
        visitor_id = row["_visitor_id"]
        if not visitor_id or row["_probe_or_noise"]:
            continue

        candidate = (row["_dt"], row["_source_row"])
        current = first_activity.get(visitor_id)

        if current is None:
            first_activity[visitor_id] = candidate
            continue

        candidate_key = (
            candidate[0] is None,
            candidate[0] or datetime.max.replace(tzinfo=UTC),
            candidate[1],
        )
        current_key = (
            current[0] is None,
            current[0] or datetime.max.replace(tzinfo=UTC),
            current[1],
        )
        if candidate_key < current_key:
            first_activity[visitor_id] = candidate

    ordered_visitor_ids = sorted(
        first_activity,
        key=lambda visitor_id: (
            first_activity[visitor_id][0] is None,
            first_activity[visitor_id][0] or datetime.max.replace(tzinfo=UTC),
            first_activity[visitor_id][1],
        ),
    )

    return {
        visitor_id: f"User {number}"
        for number, visitor_id in enumerate(ordered_visitor_ids, start=1)
    }


def output_rows(rows: list[dict]) -> list[dict[str, object]]:
    """Convert parsed rows into the readable CSV schema."""
    labels = assign_user_labels(rows)
    output: list[dict[str, object]] = []

    for row in rows:
        event = row["_event"]
        timestamp = row["_dt"]
        visitor_id = row["_visitor_id"]

        output.append(
            {
                "source_row": row["_source_row"],
                "parsed_json": yes_no(event is not None),
                "user": labels.get(visitor_id, ""),
                "visitor_id": visitor_id,
                "probe_or_noise": yes_no(row["_probe_or_noise"]),
                "time_new_york": (
                    new_york_time_text(timestamp) if timestamp is not None else ""
                ),
                "time_utc": utc_time_text(timestamp) if timestamp is not None else "",
                "level": clean_text(event.get("level")) if event else "",
                "record_type": (clean_text(event.get("record_type")) if event else ""),
                "action": clean_text(event.get("action")) if event else "",
                "friendly_action": readable_action(event),
                "details": readable_details(event, row["_raw_message"]),
                "method": clean_text(event.get("method")) if event else "",
                "url": clean_text(event.get("url")) if event else "",
                "status_code": event.get("status_code", "") if event else "",
                "request_id": (clean_text(event.get("request_id")) if event else ""),
                "raw_message": row["_raw_message"],
            }
        )

    return output


def write_all_logs(output_path: Path, rows: list[dict[str, object]]) -> None:
    """Write the all-events CSV, overwriting an existing same-day export."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # UTF-8 with BOM opens cleanly in Excel and Google Sheets.
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=ALL_LOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert one daily CloudWatch CSV into a chronological, readable "
            "all-events CSV without journey or visitor grouping."
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
            "Directory containing YYYY-MM-DD-logs.csv and the companion "
            "scripts. Defaults to the directory containing this script."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    target_date: date = args.date or datetime.now(UTC).date()
    logs_dir = (
        args.logs_dir.expanduser().resolve()
        if args.logs_dir is not None
        else Path(__file__).resolve().parent
    )

    input_path = logs_dir / f"{target_date.isoformat()}-logs.csv"
    output_path = (
        logs_dir / target_date.isoformat() / f"all-logs-{target_date.isoformat()}.csv"
    )

    if not input_path.is_file():
        raise SystemExit(
            "Required daily log file not found.\n"
            f"Expected: {input_path}\n"
            "Add a CloudWatch export named exactly "
            f"'{target_date.isoformat()}-logs.csv' and run the script again."
        )

    try:
        source_rows = load_all_rows(input_path)
        rows = output_rows(source_rows)
        write_all_logs(output_path, rows)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not export all logs: {exc}") from exc

    parsed_rows = sum(row["parsed_json"] == "Yes" for row in rows)
    noise_rows = sum(row["probe_or_noise"] == "Yes" for row in rows)
    meaningful_visitors = len(
        {str(row["visitor_id"]) for row in rows if row["user"] and row["visitor_id"]}
    )

    print(f"Target UTC date: {target_date.isoformat()}")
    print(f"Read: {input_path.name}")
    print(f"Source rows included: {len(rows)}")
    print(f"JSON rows parsed: {parsed_rows}")
    print(f"Rows marked probe/noise: {noise_rows}")
    print(f"Meaningful visitors labelled: {meaningful_visitors}")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
