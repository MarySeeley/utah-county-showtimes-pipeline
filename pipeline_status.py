"""Summarize daily liveness, sync watermarks, and warehouse contents."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import duckdb
except ImportError:
    print(
        "DuckDB is not installed. Run this with .venv\\Scripts\\python.exe.",
        file=sys.stderr,
    )
    raise SystemExit(1)

from run_pipeline import export_run_history


PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
RUN_LOG = DATA_DIR / "logs" / "pipeline_runs.jsonl"
RUNS_CSV = DATA_DIR / "logs" / "pipeline_runs.csv"
STATE_FILE = DATA_DIR / "state" / "sync_state.json"
DATABASE_PATH = DATA_DIR / "warehouse" / "utah_county_showtimes.duckdb"


def read_runs() -> list[dict]:
    if not RUN_LOG.exists():
        return []
    runs = []
    for line in RUN_LOG.read_text(encoding="utf-8").splitlines():
        if line.strip():
            runs.append(json.loads(line))
    return runs


def local_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # astimezone() without an argument uses the Windows system timezone and
    # handles daylight-saving offsets for the timestamp being converted.
    return parsed.astimezone()


def print_warehouse_counts() -> None:
    if not DATABASE_PATH.exists():
        print("Warehouse: not created yet")
        return
    con = duckdb.connect(str(DATABASE_PATH), read_only=True)
    try:
        for table in ("showtime_observations", "showtime_changes", "showtimes_current"):
            count = con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            print(f"Warehouse {table}: {count:,} rows")
    finally:
        con.close()


def print_watermarks() -> None:
    if not STATE_FILE.exists():
        print("Sync watermarks: not initialized")
        return
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    print("Sync watermarks:")
    for city, info in sorted(state.get("cities", {}).items()):
        stamp = datetime.fromisoformat(info["syncedAt"].replace("Z", "+00:00"))
        age_hours = (now - stamp.astimezone(timezone.utc)).total_seconds() / 3600
        print(f"  {city}: {info['syncedAt']} ({age_hours:.1f} hours old)")


def main() -> int:
    try:
        runs = read_runs()
        export_run_history()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Could not read the pipeline run log: {exc}", file=sys.stderr)
        return 1

    print("Utah County showtimes pipeline status")
    print(f"Recent run history CSV: {RUNS_CSV.relative_to(PROJECT_DIR)}")
    if not runs:
        print("No runs recorded yet.")
    else:
        print("Recent runs (Mountain time):")
        for run in runs[-7:]:
            timestamp = local_time(run["run_started_at_utc"]).strftime("%Y-%m-%d %I:%M %p")
            trigger = run.get("trigger", "manual/unspecified")
            received = run.get("rows_received")
            received_text = "not recorded" if received is None else str(received)
            observation_count = run.get("observation_rows")
            observation_text = "?" if observation_count is None else str(observation_count)
            current_count = run.get("current_rows")
            current_text = "?" if current_count is None else str(current_count)
            snapshot_count = len(run.get("new_raw_snapshots") or [])
            print(
                f"  {timestamp} | {run.get('status', 'unknown'):7} | "
                f"{trigger:9} | {received_text} delta rows | "
                f"{observation_text} observations | {current_text} current | "
                f"{snapshot_count} raw snapshots | "
                f"{run.get('duration_seconds', '?')} sec"
            )

        scheduled_successes = [
            run
            for run in runs
            if run.get("trigger") == "scheduled" and run.get("status") == "success"
        ]
        scheduled_days = {
            local_time(run["run_started_at_utc"]).date()
            for run in scheduled_successes
        }
        print(
            f"Successful scheduled runs on distinct days: "
            f"{len(scheduled_days)}"
        )
        if len(scheduled_days) < 2:
            print("Liveness demo: collect at least two scheduled runs on separate days.")
        else:
            print("Liveness demo: multiple scheduled days are recorded.")

    print_warehouse_counts()
    print_watermarks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
