"""Load transformed CSVs into a local DuckDB analytical warehouse."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

try:
    import duckdb
except ImportError:
    print(
        "DuckDB is not installed. From DataPipeline, run: "
        "python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1)


PROJECT_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
WAREHOUSE_DIR = PROJECT_DIR / "data" / "warehouse"
DATABASE_PATH = WAREHOUSE_DIR / "utah_county_showtimes.duckdb"


def csv_columns(path: Path) -> list[str]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle))


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def make_stage(con, table_name: str, csv_path: Path) -> list[str]:
    columns = csv_columns(csv_path)
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {quote_identifier(table_name)} AS "
        f"SELECT * FROM read_csv({sql_string(csv_path.as_posix())}, "
        "header = true, all_varchar = true, nullstr = '')"
    )
    return columns


def create_table(con, table_name: str, columns: list[str], key_columns: list[str], prefix: list[str] | None = None) -> None:
    definitions = [f"{quote_identifier(column)} VARCHAR" for column in columns]
    if prefix:
        definitions = prefix + definitions
    key_sql = ", ".join(quote_identifier(column) for column in key_columns)
    definitions.append(f"PRIMARY KEY ({key_sql})")
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {quote_identifier(table_name)} "
        f"({', '.join(definitions)})"
    )


def insert_columns(columns: list[str]) -> str:
    return ", ".join(quote_identifier(column) for column in columns)


def load() -> dict[str, int]:
    observation_csv = PROCESSED_DIR / "showtime_observations.csv"
    current_csv = PROCESSED_DIR / "showtimes_current.csv"
    changes_csv = PROCESSED_DIR / "showtime_changes.csv"
    for path in (observation_csv, current_csv, changes_csv):
        if not path.exists():
            raise FileNotFoundError(f"Missing transformed input: {path}")

    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DATABASE_PATH))
    try:
        con.execute("BEGIN TRANSACTION")

        observations = make_stage(con, "stage_observations", observation_csv)
        create_table(
            con,
            "showtime_observations",
            observations,
            ["source_snapshot", "showtime_id"],
        )
        columns_sql = insert_columns(observations)
        con.execute(
            f"INSERT INTO showtime_observations ({columns_sql}) "
            f"SELECT {columns_sql} FROM stage_observations ON CONFLICT DO NOTHING"
        )

        current = make_stage(con, "stage_current", current_csv)
        create_table(con, "showtimes_current", current, ["showtime_id"])
        con.execute("DELETE FROM showtimes_current")
        current_sql = insert_columns(current)
        con.execute(
            f"INSERT INTO showtimes_current ({current_sql}) "
            f"SELECT {current_sql} FROM stage_current"
        )

        changes = make_stage(con, "stage_changes", changes_csv)
        hash_input = ", ".join(
            f"coalesce({quote_identifier(column)}, '')" for column in changes
        )
        con.execute(
            "CREATE OR REPLACE TEMP TABLE stage_changes_with_key AS "
            "SELECT md5(concat_ws(chr(31), " + hash_input + ")) AS event_key, * "
            "FROM stage_changes"
        )
        create_table(
            con,
            "showtime_changes",
            changes,
            ["event_key"],
            prefix=['"event_key" VARCHAR'],
        )
        changes_sql = insert_columns(changes)
        con.execute(
            f"INSERT INTO showtime_changes (event_key, {changes_sql}) "
            f"SELECT event_key, {changes_sql} FROM stage_changes_with_key "
            "ON CONFLICT DO NOTHING"
        )

        con.execute("COMMIT")
        counts = {}
        for table in ("showtime_observations", "showtimes_current", "showtime_changes"):
            counts[table] = con.execute(
                f"SELECT count(*) FROM {quote_identifier(table)}"
            ).fetchone()[0]
        return counts
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def main() -> int:
    try:
        counts = load()
    except Exception as exc:
        print(f"Warehouse load failed: {exc}", file=sys.stderr)
        return 1

    print(f"DuckDB warehouse: {DATABASE_PATH.relative_to(PROJECT_DIR)}")
    for table, count in counts.items():
        print(f"{table}: {count} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
