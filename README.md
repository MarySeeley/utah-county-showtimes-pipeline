# Utah County Showtimes Pipeline

The collector covers active API-Cinema listings in nine Utah County cities:
Provo, Orem, American Fork, Lehi, Payson, Pleasant Grove, Saratoga Springs,
Spanish Fork, and Vineyard. It keeps an independent watermark for each city.

## Run it

From PowerShell in this folder, install the dependency once:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run a complete collect, transform, and warehouse load:

```powershell
.\.venv\Scripts\python.exe .\run_pipeline.py
```

A generated dashboard snapshot is included at `showtimes_dashboard.html`; download and open it in a browser to inspect the captured schedule. The runner refreshes the working dashboard at
`data/visualization/showtimes_dashboard.html`. Open that file in a browser to
filter upcoming shows by date, city, and theater, compare busy titles and
venues, inspect start-time patterns and source-provided format/version tags,
compare movie showtimes within a rolling seven-day window starting today,
and rank theaters by recorded reschedules and removals. Its two-week activity
chart shows collected days with no changes, missing collection days, and the next
seven days as they fill in. Showtimes outside the seven-day window are excluded
because theater schedules may be incomplete farther out. Initial imports and first-seen showtimes are
excluded from the reschedule/removal counts. To rebuild the dashboard without
collecting new API data, run:

```powershell
.\.venv\Scripts\python.exe .\generate_dashboard.py
```

The source does not provide movie ratings or ticket prices, so the dashboard
does not show those as if they were collected values.

Register the Windows Task Scheduler job (9:00 a.m. local time plus a sign-in catch-up trigger):

```powershell
.\install_daily_task.ps1
```

The task runs as your Windows user while you are signed in. It starts at 9:00 a.m. or when you sign in if no successful scheduled run is recorded for that Mountain Time date. If both triggers fire on the same date, the runner guard prevents a second collection. The run log is appended to `data/logs/pipeline_runs.jsonl`.

Check run freshness, recent delta sizes, saved watermarks, and warehouse totals with:

```powershell
.\.venv\Scripts\python.exe .\pipeline_status.py
```

The runner labels Task Scheduler daily and sign-in launches as `scheduled`; the status report counts successful scheduled runs on distinct local dates. The guard uses the Mountain Time date and skips a second scheduled collection after a success that day. Run it after two scheduled runs on distinct dates to prepare the assignment's liveness demo. It also exports `data/logs/pipeline_runs.csv`, which can be graphed in a spreadsheet.

The runner uses the virtual environment automatically when it exists. The API key is read from `config.secret.json` or the `API_CINEMA_KEY` environment variable. Keep the key out of source control.

The requirements include `tzdata` so Windows Python can resolve IANA timezone names such as `America/Denver`. The transformer reports a missing timezone database as an error instead of silently dropping upcoming showtimes.

## Pipeline layers

| Layer | Location | Purpose |
| --- | --- | --- |
| Raw | `data/raw/*.json` | Keep each API response as received so it can be reprocessed. |
| State | `data/state/sync_state.json` | Store the API watermarks used to request later changes. |
| Transformed | `data/processed/*.csv` | Flatten API records into observation history, current showtimes, and change events. |
| Warehouse | `data/warehouse/utah_county_showtimes.duckdb` | Query the transformed data with SQL. |
| Operations | `data/logs/pipeline_runs.jsonl` | Track each run's status, duration, and row counts. |

`showtime_observations` and `showtime_changes` are append-only and use unique keys, so loading the same files again does not add duplicate rows. `showtimes_current` is replaced from the latest transformed current view on each load. The loader wraps its changes in a transaction so a failed load does not leave a half-updated current view.

The API sync is incremental. Daily raw files preserve exactly what the source sent, including empty deltas; the warehouse's observation and change tables preserve new or changed records. An unchanged showtime is not copied into history every day. This gives us a record of source-reported history without spending the request quota on repeated full snapshots.

Recovery behavior and the system diagram are documented in `architecture.md`. The collector falls back to a full city sync if it has missed more than the API's 30-day tombstone window; the expired watermark cannot safely recover old removal events.

To explore the warehouse, open `warehouse_queries.sql` in a DuckDB client connected to `data/warehouse/utah_county_showtimes.duckdb`.

## Source limits to account for

The API provides showtimes and booking links, not prices. Its US theater data is refreshed every one to three days and the source retains past showtimes for only a short period. This pipeline builds historical observations from the time collection begins; it cannot reconstruct older history the API no longer has. City filtering is kept to one city per request because the API documents multi-city filters as a Pro-plan feature.
