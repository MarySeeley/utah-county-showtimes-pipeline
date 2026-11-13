"""Import or incrementally sync upcoming Utah County showtimes."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://api.api-cinema.com/v1"
CITIES = (
    "Provo",
    "Orem",
    "American Fork",
    "Lehi",
    "Payson",
    "Pleasant Grove",
    "Saratoga Springs",
    "Spanish Fork",
    "Vineyard",
)
# The API supports showtime pages up to 1,000 rows; larger pages reduce
# request usage for the additional city scopes while retaining cursor safety.
PAGE_SIZE = 1000
TOMBSTONE_RETENTION = timedelta(days=30)
PROJECT_DIR = Path(__file__).resolve().parent
SECRET_FILE = PROJECT_DIR / "config.secret.json"
DATA_DIR = PROJECT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
STATE_FILE = DATA_DIR / "state" / "sync_state.json"


def load_api_key() -> str:
    """Read the key from the environment first, then the local secret file."""
    key = os.environ.get("API_CINEMA_KEY")
    if not key and SECRET_FILE.exists():
        config = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        key = config.get("apiCinema")

    if not isinstance(key, str) or not key.strip():
        raise RuntimeError(
            "Set API_CINEMA_KEY or add a non-empty apiCinema field to "
            "DataPipeline/config.secret.json."
        )
    return key.strip()


def get_json(path: str, params: dict[str, str], api_key: str) -> dict:
    request = Request(
        f"{BASE_URL}{path}?{urlencode(params)}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "UtahCountyShowtimePipeline/0.2 (educational project)",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            error_code = json.load(exc).get("error", {}).get("code", "unknown")
        except (json.JSONDecodeError, AttributeError):
            error_code = "unknown"
        raise RuntimeError(
            f"API request failed with HTTP {exc.code} ({error_code}) for {path}."
        ) from None
    except URLError as exc:
        raise RuntimeError(f"Could not reach the showtimes API ({exc.reason}).") from None


def fetch_pages(path: str, params: dict[str, str], api_key: str) -> dict:
    """Fetch all pages and retain the original page envelopes and sync metadata."""
    pages = []
    rows = []
    next_params = {**params, "limit": str(PAGE_SIZE)}
    first_meta = None

    while True:
        payload = get_json(path, next_params, api_key)
        pages.append(payload)
        rows.extend(payload.get("data", []))
        if first_meta is None:
            first_meta = payload.get("meta", {})
        cursor = payload.get("meta", {}).get("nextCursor")
        if not cursor:
            break
        next_params = {**params, "limit": str(PAGE_SIZE), "cursor": cursor}

    return {"data": rows, "meta": first_meta or {}, "pages": pages}


def load_sync_state() -> dict:
    if not STATE_FILE.exists():
        return {"cities": {}}
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    # A previous version tracked per-cinema imports, but the provider only
    # documents updated_since on the general /showtimes endpoint. Start a
    # fresh city-scoped full import when migrating that older state format.
    if "cities" not in state:
        return {"cities": {}}
    if not isinstance(state.get("cities"), dict):
        raise ValueError("Sync state file is malformed; refusing to overwrite it.")
    return state


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def collect() -> tuple[dict, dict]:
    api_key = load_api_key()
    collected_at = datetime.now(timezone.utc).isoformat()
    old_state = load_sync_state()
    next_state = {"cities": dict(old_state["cities"])}

    sync_responses = []
    for city in CITIES:
        saved_watermark = old_state["cities"].get(city, {}).get("syncedAt")
        query = {"country": "US", "city": city}
        mode = "full"
        reason = "initial_full_import"
        if saved_watermark:
            try:
                parsed_watermark = datetime.fromisoformat(
                    saved_watermark.replace("Z", "+00:00")
                )
            except (AttributeError, ValueError):
                raise ValueError(f"Saved sync watermark for {city} is malformed.") from None
            if parsed_watermark.tzinfo is None:
                raise ValueError(f"Saved sync watermark for {city} has no timezone.")
            watermark_age = datetime.now(timezone.utc) - parsed_watermark.astimezone(timezone.utc)
            if timedelta(0) <= watermark_age <= TOMBSTONE_RETENTION:
                query["updated_since"] = saved_watermark
                mode = "incremental"
                reason = "watermark_within_retention"
            else:
                # Tombstones expire after 30 days, so a very old or future
                # watermark cannot safely recover missed removals.
                reason = "watermark_expired_or_future_full_resync"

        response = fetch_pages("/showtimes", query, api_key)
        new_watermark = response["meta"].get("syncedAt")
        if not new_watermark:
            raise RuntimeError(
                f"The provider omitted meta.syncedAt for {city}; "
                "sync state was not advanced."
            )

        sync_responses.append(
            {
                "mode": mode,
                "reason": reason,
                "scope_city": city,
                "query": query,
                "syncedAt": new_watermark,
                "pages": response["pages"],
                "data": response["data"],
            }
        )
        next_state["cities"][city] = {
            "syncedAt": new_watermark,
        }

    next_state["lastSuccessAtUtc"] = collected_at
    snapshot = {
        "collectedAtUtc": collected_at,
        "source": "API Cinema",
        "scope": {"country": "US", "region": "Utah County", "cities": list(CITIES)},
        "syncResponses": sync_responses,
    }
    return snapshot, next_state


def main() -> int:
    try:
        snapshot, next_state = collect()
    except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        return 1

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = RAW_DIR / f"showtimes_{stamp}.json"
    write_json_atomic(output_path, snapshot)
    # Advance watermarks only after the raw responses are safely persisted.
    write_json_atomic(STATE_FILE, next_state)

    modes = [response["mode"] for response in snapshot["syncResponses"]]
    row_count = sum(len(response["data"]) for response in snapshot["syncResponses"])
    removed_count = sum(
        1
        for response in snapshot["syncResponses"]
        for showtime in response["data"]
        if showtime.get("removedAt")
    )
    print(f"Saved raw sync: {output_path.relative_to(PROJECT_DIR)}")
    print(f"City scopes synced: {len(modes)}; rows received: {row_count}; removals: {removed_count}")
    print(f"Modes: {', '.join(modes)}")
    print(f"Watermarks saved: {STATE_FILE.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
