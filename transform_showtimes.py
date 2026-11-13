"""Flatten raw API snapshots into observation history and a current view."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PROJECT_DIR = Path(__file__).resolve().parent
RAW_DIR = PROJECT_DIR / "data" / "raw"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
STATE_FIELDS = [
    "cinema_id",
    "cinema_name",
    "city",
    "timezone",
    "movie_id",
    "movie_title",
    "starts_at_local",
    "screening_version",
    "format",
    "room",
    "booking_url",
]

FIELDS = [
    "observed_at_utc",
    "source_snapshot",
    "sync_mode",
    "showtime_id",
    "cinema_id",
    "cinema_name",
    "city",
    "postal_code",
    "timezone",
    "movie_id",
    "movie_title",
    "tmdb_id",
    "starts_at_local",
    "screening_version",
    "format",
    "room",
    "booking_url",
    "source_updated_at_utc",
    "source_removed_at_utc",
    "ticket_price",
    "currency",
    "price_status",
]
CHANGE_FIELDS = [
    "event_observed_at_utc",
    "event_type",
    "showtime_id",
    "cinema_id",
    "cinema_name",
    "movie_id",
    "movie_title",
    "changed_fields",
    "previous_starts_at_local",
    "starts_at_local",
    "previous_format",
    "format",
    "previous_screening_version",
    "screening_version",
    "previous_room",
    "room",
    "source_updated_at_utc",
    "source_removed_at_utc",
]


def read_snapshots() -> list[tuple[datetime, Path, dict]]:
    snapshots = []
    for path in sorted(RAW_DIR.glob("showtimes_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        collected_at = payload.get("collectedAtUtc")
        if not collected_at:
            raise ValueError(f"Snapshot has no collectedAtUtc value: {path.name}")
        timestamp = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
        snapshots.append((timestamp, path, payload))
    return snapshots


def flatten_records(
    snapshot_time: str,
    snapshot_path: Path,
    cinema: dict,
    showtimes: list[dict],
    sync_mode: str,
) -> list[dict]:
    rows = []
    for showtime in showtimes:
        movie = showtime.get("movie") or {}
        embedded_cinema = showtime.get("cinema") or cinema
        rows.append(
            {
                "observed_at_utc": snapshot_time,
                "source_snapshot": snapshot_path.name,
                "sync_mode": sync_mode,
                "showtime_id": showtime.get("id"),
                "cinema_id": showtime.get("cinemaId") or embedded_cinema.get("id"),
                "cinema_name": embedded_cinema.get("name"),
                "city": embedded_cinema.get("city"),
                "postal_code": embedded_cinema.get("postalCode"),
                "timezone": embedded_cinema.get("timezone"),
                "movie_id": showtime.get("movieId") or movie.get("id"),
                "movie_title": movie.get("title"),
                "tmdb_id": movie.get("tmdbId"),
                "starts_at_local": showtime.get("startsAt"),
                "screening_version": showtime.get("version"),
                "format": showtime.get("format"),
                "room": showtime.get("room"),
                "booking_url": showtime.get("bookingUrl"),
                "source_updated_at_utc": showtime.get("updatedAt"),
                "source_removed_at_utc": showtime.get("removedAt"),
                # Empty price plus an explicit status means unknown, not $0.
                "ticket_price": "",
                "currency": "",
                "price_status": "not_provided_by_showtimes_source",
            }
        )
    return rows


def response_groups(snapshot_time: str, snapshot_path: Path, payload: dict) -> list[dict]:
    """Normalize legacy full snapshots and new per-cinema sync responses."""
    groups = []
    if payload.get("syncResponses"):
        for response in payload["syncResponses"]:
            groups.append(
                {
                    "mode": response.get("mode", "incremental"),
                    "cinema": response.get("cinema", {}),
                    "scope_city": response.get("scope_city"),
                    "rows": flatten_records(
                        snapshot_time,
                        snapshot_path,
                        response.get("cinema", {}),
                        response.get("data", []),
                        response.get("mode", "incremental"),
                    ),
                }
            )
        return groups

    # Older files contain a complete response per cinema; treat each file as
    # a full snapshot for backward-compatible history reconstruction.
    rows = []
    for response in payload.get("showtimeResponses", []):
        rows.extend(
            flatten_records(
                snapshot_time,
                snapshot_path,
                response.get("cinema", {}),
                response.get("data", []),
                "full",
            )
        )
    groups.append({"mode": "full", "cinema": {}, "rows": rows})
    return groups


def is_upcoming(row: dict) -> bool:
    try:
        start = datetime.fromisoformat(row["starts_at_local"])
        zone = ZoneInfo(row["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            "Python has no IANA timezone database for "
            f"{row.get('timezone')!r}; install project requirements (tzdata)."
        ) from exc
    except (TypeError, ValueError, KeyError):
        return False
    return start.replace(tzinfo=zone) >= datetime.now(zone)


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def change_event(event_type: str, observed: dict, previous: dict | None, changed: list[str]) -> dict:
    previous = previous or {}
    return {
        "event_observed_at_utc": observed["observed_at_utc"],
        "event_type": event_type,
        "showtime_id": observed["showtime_id"],
        "cinema_id": observed["cinema_id"],
        "cinema_name": observed["cinema_name"],
        "movie_id": observed["movie_id"],
        "movie_title": observed["movie_title"],
        "changed_fields": ";".join(changed),
        "previous_starts_at_local": previous.get("starts_at_local"),
        "starts_at_local": observed["starts_at_local"],
        "previous_format": previous.get("format"),
        "format": observed["format"],
        "previous_screening_version": previous.get("screening_version"),
        "screening_version": observed["screening_version"],
        "previous_room": previous.get("room"),
        "room": observed["room"],
        "source_updated_at_utc": observed["source_updated_at_utc"],
        "source_removed_at_utc": observed["source_removed_at_utc"],
    }


def main() -> int:
    try:
        snapshots = read_snapshots()
        if not snapshots:
            raise ValueError(f"No raw snapshots found under {RAW_DIR}")

        snapshots.sort(key=lambda item: item[0])
        history_rows: list[dict] = []
        change_rows: list[dict] = []
        previous_state_by_id: dict[str, dict] = {}
        removal_events_seen: set[tuple[str, str]] = set()
        duplicate_observations = 0

        for _, path, payload in snapshots:
            observed_at = payload["collectedAtUtc"]
            for group in response_groups(observed_at, path, payload):
                rows = group["rows"]
                mode = group["mode"]
                cinema_id = group["cinema"].get("id")
                scope_city = group.get("scope_city")

                # A full import replaces that cinema's state. Older snapshot
                # files do not have a cinema-level group, so they replace all.
                if mode == "full":
                    if cinema_id:
                        previous_state_by_id = {
                            showtime_id: state
                            for showtime_id, state in previous_state_by_id.items()
                            if state.get("cinema_id") != cinema_id
                        }
                    elif scope_city:
                        previous_state_by_id = {
                            showtime_id: state
                            for showtime_id, state in previous_state_by_id.items()
                            if state.get("city") != scope_city
                        }
                    else:
                        previous_state_by_id.clear()

                seen_in_group: set[str] = set()
                for row in rows:
                    showtime_id = row["showtime_id"]
                    observation_key = f"{row['cinema_id']}:{showtime_id}"
                    if observation_key in seen_in_group:
                        duplicate_observations += 1
                        continue
                    seen_in_group.add(observation_key)
                    history_rows.append(row)

                    if not showtime_id:
                        continue

                    previous = previous_state_by_id.get(showtime_id)
                    state = dict(row)
                    removed_at = row["source_removed_at_utc"]
                    if removed_at:
                        removal_key = (showtime_id, removed_at)
                        if removal_key not in removal_events_seen:
                            change_rows.append(change_event("removed", row, previous, []))
                            removal_events_seen.add(removal_key)
                        previous_state_by_id.pop(showtime_id, None)
                        continue

                    if previous is None:
                        change_rows.append(change_event("first_seen", row, None, STATE_FIELDS))
                    else:
                        changed = [field for field in STATE_FIELDS if previous.get(field) != state[field]]
                        if changed:
                            change_rows.append(change_event("changed", row, previous, changed))
                    previous_state_by_id[showtime_id] = state

        current_rows_by_id = {
            showtime_id: state
            for showtime_id, state in previous_state_by_id.items()
            if is_upcoming(state)
        }

        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        history_path = PROCESSED_DIR / "showtime_observations.csv"
        current_path = PROCESSED_DIR / "showtimes_current.csv"
        changes_path = PROCESSED_DIR / "showtime_changes.csv"
        write_csv(history_path, history_rows, FIELDS)
        write_csv(current_path, list(current_rows_by_id.values()), FIELDS)
        write_csv(changes_path, change_rows, CHANGE_FIELDS)

        print(f"Snapshots read: {len(snapshots)}")
        print(f"Observation history rows: {len(history_rows)}")
        print(f"Latest snapshot: {snapshots[-1][1].name}")
        print(f"Current showtimes: {len(current_rows_by_id)}")
        print(f"First-seen/change/removal events: {len(change_rows)}")
        print(f"Change-event output: {changes_path.relative_to(PROJECT_DIR)}")
        print(f"Duplicate rows skipped within snapshots: {duplicate_observations}")
        print(f"History output: {history_path.relative_to(PROJECT_DIR)}")
        print(f"Current output: {current_path.relative_to(PROJECT_DIR)}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Transformation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
