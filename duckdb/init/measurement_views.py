#!/usr/bin/env python3
"""Build /data/measurements.duckdb for the Grafana dashboard.

device_series: a table with one row per device and measurement series
(counts, first/last time, unit). Grafana's Device and Series dropdowns read
it; answering "which device has data in which per-fragment table" any other
way means scanning every table in polaris.cdc_measurement.

series_sql: one row per series (metric, sql), where sql selects that series
as (time, source, metric, value, unit). Dashboard panels join the rows of the
selected series with UNION ALL and run them via query(getvariable(...)), so
DuckDB only loads the selected tables.

series_values: a view with all series in one long table (time, source,
metric, value, unit), for ad-hoc SQL. Not used by the dashboard: binding it
loads every measurement table (~2 s per query, 20-40 s cold).

Every Cumulocity measurement fragment is its own Iceberg table, with one
struct column per series (`<series>`.value, optionally .unit). The SQL is
generated from that layout, so re-run this script (`docker compose run --rm
duckdb-init`) when new measurement types appear or to refresh device_series,
then restart Grafana, which keeps the old file open.

Same layout as starrocks/init/device_series.py.
"""
import os
import re
import sys
import duckdb

SCHEMA = "cdc_measurement"
TARGET = "/data/measurements.duckdb"
BASE_COLUMNS = {"id", "source", "eventType", "time", "type"}
SEP = " · "  # device label = "<name> · <id>"; names are not unique

WAREHOUSE = os.environ["POLARIS_WAREHOUSE"]
URI = os.environ["POLARIS_URI"]


def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def pretty(name: str) -> str:
    # Cumulocity XML-escapes special characters in fragment names: _x0020 -> " "
    return re.sub(r"_x([0-9A-Fa-f]{4})_?", lambda m: chr(int(m.group(1), 16)), name)


def discover(con) -> list:
    """[(table, struct column, has_unit, metric label)] for every measurement series."""
    tables = [t for (t,) in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE database_name = 'polaris' AND schema_name = ? "
        "ORDER BY table_name", [SCHEMA]).fetchall()]
    series = []
    for table in tables:
        # DESCRIBE loads the table; duckdb_columns() only has placeholders until then
        for column, ctype, *_ in con.execute(f"DESCRIBE polaris.{SCHEMA}.{ident(table)}").fetchall():
            ctype = ctype.upper()
            if column not in BASE_COLUMNS and ctype.startswith("STRUCT(") and '"VALUE"' in ctype:
                series.append((table, column, " UNIT " in ctype, f"{table}.{pretty(column)}"))
    if not series:
        sys.exit(f"no measurement series found in polaris.{SCHEMA}")
    return series


def device_names(con) -> str:
    """Subquery (id, name) of the current inventory."""
    try:
        con.execute("SELECT id, name FROM polaris.latest_inventory.inventory LIMIT 1").fetchall()
        return "SELECT id, name FROM polaris.latest_inventory.inventory"
    except duckdb.Error as e:
        # latest_inventory uses equality deletes; fall back to the CDC log
        print(f"[views] latest_inventory not readable ({str(e).splitlines()[0]}), using cdc_inventory")
        return ("SELECT id, name FROM polaris.cdc_inventory.inventory "
                "QUALIFY ROW_NUMBER() OVER (PARTITION BY id ORDER BY lastUpdated DESC) = 1")


def device_series_sql(series, names) -> str:
    branches = []
    for table, column, has_unit, metric in series:
        unit = f"MAX({ident(column)}.unit)" if has_unit else "CAST(NULL AS VARCHAR)"
        branches.append(
            f"  SELECT source, {literal(table)} AS fragment, {literal(column)} AS series_column,\n"
            f"         {literal(pretty(column))} AS series, {literal(metric)} AS metric, {unit} AS unit,\n"
            f"         COUNT(*) AS measurements, MIN(time) AS first_time, MAX(time) AS last_time\n"
            f"  FROM polaris.{SCHEMA}.{ident(table)}\n"
            f"  WHERE eventType = 'MEASUREMENT_CREATE' AND {ident(column)}.value IS NOT NULL\n"
            f"  GROUP BY source")
    return (
        "CREATE TABLE device_series AS\n"
        "SELECT s.source AS device_id,\n"
        f"       CASE WHEN i.name IS NULL THEN s.source ELSE i.name || '{SEP}' || s.source END AS device,\n"
        "       s.fragment, s.series_column, s.series, s.metric, s.unit,\n"
        "       s.measurements, s.first_time, s.last_time\n"
        "FROM (\n" + "\n  UNION ALL\n".join(branches) + "\n) s\n"
        f"LEFT JOIN ({names}) i ON i.id = s.source")


def branch_sql(table, column, has_unit, metric) -> str:
    unit = f"{ident(column)}.unit" if has_unit else "CAST(NULL AS VARCHAR)"
    return (f"SELECT time, source, {literal(metric)} AS metric, "
            f"CAST({ident(column)}.value AS DOUBLE) AS value, {unit} AS unit "
            f"FROM polaris.{SCHEMA}.{ident(table)} "
            f"WHERE eventType = 'MEASUREMENT_CREATE' AND {ident(column)}.value IS NOT NULL")


def series_values_sql(series) -> str:
    return "CREATE VIEW series_values AS\n" + "\nUNION ALL\n".join(branch_sql(*s) for s in series)


def create_series_sql(con, series):
    con.execute("CREATE TABLE series_sql (metric VARCHAR PRIMARY KEY, sql VARCHAR)")
    con.executemany("INSERT INTO series_sql VALUES (?, ?)", [(s[3], branch_sql(*s)) for s in series])


def main():
    tmp = TARGET + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    # Build in a new file and swap it in, so a running Grafana (read-only) isn't blocked
    con = duckdb.connect(tmp)
    # Path-style S3 URLs: virtual-hosted ones fail TLS for bucket names with dots
    con.execute("LOAD iceberg; LOAD httpfs; SET s3_url_style = 'path';")
    con.execute(f"ATTACH '{WAREHOUSE}' AS polaris (TYPE ICEBERG, ENDPOINT '{URI}', "
                "ACCESS_DELEGATION_MODE 'vended_credentials')")
    series = discover(con)
    con.execute(device_series_sql(series, device_names(con)))
    con.execute(series_values_sql(series))
    create_series_sql(con, series)
    pairs, devices = con.execute("SELECT COUNT(*), COUNT(DISTINCT device_id) FROM device_series").fetchone()
    con.close()
    os.replace(tmp, TARGET)
    print(f"[views] {TARGET}: {len({s[0] for s in series})} tables, {len(series)} series, "
          f"{pairs} device/series pairs, {devices} devices")


if __name__ == "__main__":
    main()
