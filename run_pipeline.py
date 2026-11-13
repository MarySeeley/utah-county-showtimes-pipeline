"""Run one collect-transform cycle and append a safe operational run log."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_DIR = Path(__file__).resolve().parent
RAW_DIR = PROJECT_DIR / "data" / "raw"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
RUN_LOG = PROJECT_DIR / "data" / "logs" / "pipeline_runs.jsonl"
RUNS_CSV = PROJECT_DIR / "data" / "logs" / "pipeline_runs.csv"
VENV_PYTHON = PROJECT_DIR / ".venv" / (
    "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
)
MOUNTAIN_TIME = ZoneInfo("America/Denver")
RUN_FIELDS = [
    "run_started_at_utc",
    "run_finished_at_utc",
    "trigger",
    "status",
    "duration_seconds",
    "sync_modes",
    "rows_received",
    "removals_received",
    "new_raw_snapshot_count",
    "observation_rows",
    "current_rows",
    "change_event_rows",
    "error_stage",
]


def export_run_history() -> None:
    runs = []
    if RUN_LOG.exists():
        for line in RUN_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                runs.append(json.loads(line))
    temporary = RUNS_CSV.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for run in runs:
            writer.writerow(
                {
                    **run,
                    "sync_modes": ";".join(run.get("sync_modes") or []),
                    "new_raw_snapshot_count": len(run.get("new_raw_snapshots") or []),
                }
            )
    temporary.replace(RUNS_CSV)


def csv_data_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return max(sum(1 for _ in csv.reader(handle)) - 1, 0)


def successful_scheduled_run_today(now: datetime) -> bool:
    """Return whether this Mountain-local date already has a scheduled success."""
    if not RUN_LOG.exists():
        return False
    local_date = now.astimezone(MOUNTAIN_TIME).date()
    for line in RUN_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            run = json.loads(line)
            if run.get("trigger") != "scheduled" or run.get("status") != "success":
                continue
            finished_at = datetime.fromisoformat(
                run["run_finished_at_utc"].replace("Z", "+00:00")
            )
            if finished_at.astimezone(MOUNTAIN_TIME).date() == local_date:
                return True
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one collection and warehouse cycle.")
    parser.add_argument(
        "--trigger",
        choices=("manual", "scheduled"),
        default="manual",
        help="Label the run so scheduled executions can be distinguished in the liveness report.",
    )
    args = parser.parse_args()

    if args.trigger == "scheduled":
        scheduled_now = datetime.now(MOUNTAIN_TIME)
        if successful_scheduled_run_today(scheduled_now):
            print(
                "Scheduled run skipped: a successful scheduled run is already "
                f"recorded for {scheduled_now.date()} Mountain time."
            )
            return 0

    started = datetime.now(timezone.utc)
    started_clock = time.monotonic()
    raw_before = set(RAW_DIR.glob("showtimes_*.json"))
    record = {
        "run_started_at_utc": started.isoformat(),
        "trigger": args.trigger,
        "status": "running",
        "collector_exit_code": None,
        "transformer_exit_code": None,
        "warehouse_exit_code": None,
        "dashboard_exit_code": None,
        "new_raw_snapshots": [],
        "sync_modes": [],
        "rows_received": None,
        "removals_received": None,
        "observation_rows": None,
        "current_rows": None,
        "change_event_rows": None,
        "error_stage": None,
    }

    try:
        for stage, script, exit_field in (
            ("collector", "collect_showtimes.py", "collector_exit_code"),
            ("transformer", "transform_showtimes.py", "transformer_exit_code"),
            ("warehouse", "load_warehouse.py", "warehouse_exit_code"),
            ("dashboard", "generate_dashboard.py", "dashboard_exit_code"),
        ):
            result = subprocess.run(
                [str(VENV_PYTHON if VENV_PYTHON.is_file() else sys.executable), str(PROJECT_DIR / script)],
                cwd=PROJECT_DIR,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
                if stage == "collector":
                    counts = re.search(
                        r"rows received: (\d+); removals: (\d+)", result.stdout
                    )
                    if counts:
                        record["rows_received"] = int(counts.group(1))
                        record["removals_received"] = int(counts.group(2))
                    modes = re.search(r"^Modes: (.+)$", result.stdout, re.MULTILINE)
                    if modes:
                        record["sync_modes"] = [
                            value.strip() for value in modes.group(1).split(",")
                        ]
            if result.stderr:
                print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
            record[exit_field] = result.returncode
            if result.returncode:
                record["status"] = "failed"
                record["error_stage"] = stage
                break
        else:
            record["status"] = "success"

        record["new_raw_snapshots"] = sorted(
            path.name for path in set(RAW_DIR.glob("showtimes_*.json")) - raw_before
        )
        record["observation_rows"] = csv_data_rows(PROCESSED_DIR / "showtime_observations.csv")
        record["current_rows"] = csv_data_rows(PROCESSED_DIR / "showtimes_current.csv")
        record["change_event_rows"] = csv_data_rows(PROCESSED_DIR / "showtime_changes.csv")
    except OSError as exc:
        record["status"] = "failed"
        record["error_stage"] = "runner"
        # Keep operational logs useful without copying arbitrary process output
        # or configuration values into the log.
        print(f"Pipeline runner failed: {exc}", file=sys.stderr)

    finished = datetime.now(timezone.utc)
    record["run_finished_at_utc"] = finished.isoformat()
    record["duration_seconds"] = round(time.monotonic() - started_clock, 3)
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    export_run_history()

    print(f"Pipeline status: {record['status']}")
    print(f"Run log: {RUN_LOG.relative_to(PROJECT_DIR)}")
    print(f"Run history CSV: {RUNS_CSV.relative_to(PROJECT_DIR)}")
    if record["status"] != "success":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
