# DuckDB

Query the Polaris catalog with DuckDB's `iceberg` extension and chart measurements in Grafana.
Polaris vends short-lived S3 credentials per table, so no AWS keys are stored.

```
Grafana (port 3000)  [DuckDB plugin, in-memory DuckDB]
    ├── measurements.duckdb   device_series and series_sql tables
    └── Polaris REST Catalog  (OAuth2 client-credentials)
            └── S3  (vended credentials)
```

## Setup

```bash
cd duckdb
cp .env.example .env   # fill in the Polaris credentials and a Grafana password
docker compose up -d
```

`duckdb-init` stores the OAuth secret, checks the catalog and builds `/data/measurements.duckdb`.
Grafana starts once it's done: **http://localhost:3000** (user `admin`). The **Cumulocity /
Measurements** dashboard is the home page: pick a device, one or more series, and a time range.

## Grafana

- Plugin: [motherduck-duckdb-datasource](https://github.com/motherduckdb/grafana-duckdb-datasource)
  v0.4.5 (unsigned, needs the Ubuntu Grafana image; see `Dockerfile.grafana`). It bundles DuckDB
  1.5.4; `Dockerfile.duckdb` uses 1.5.6, which writes files 1.5.4 can read (same 1.5 storage format).
  Keep both on the same minor version.
- The data source (`grafana/provisioning/datasources/duckdb.yaml`) runs init SQL on an
  in-memory DuckDB: Polaris secret and `ATTACH`, plus `measurements.duckdb` read-only.
- Panels don't read all measurement tables: `series_sql` holds one `SELECT` per series, and
  each panel joins those of the selected series and runs them with
  `query(getvariable('series_query'))`, so DuckDB only opens the selected tables (a view over
  all 23 tables costs ~2 s per query, 20–40 s right after a start).
- The plugin runs queries one at a time. The first load after a start takes up to ~40 s
  (Iceberg metadata not cached yet), so `GF_DATAPROXY_TIMEOUT=120` raises Grafana's 30 s
  limit; later loads take a few seconds.
- Dashboard SQL uses `'${device:raw}'`: the plugin quotes plain `${device}` itself.
- `device_series` is a snapshot. Refresh it, and pick up new measurement types, with:

  ```bash
  docker compose run --rm duckdb-init && docker compose restart grafana
  ```

## DuckDB CLI

```bash
docker exec -it duckdb duckdb -init /data/duckdbrc.sql
SELECT * FROM polaris.cdc_measurement."bearingTemperature" ORDER BY time DESC LIMIT 5;
```

## Limitations

- **No metadata caching across sessions.** Every new DuckDB process (CLI session, Grafana
  restart) loads each Iceberg table's metadata again from Polaris and S3, about 1–2 s per
  table; touching all 23 measurement tables cold took 43 s. StarRocks caches table metadata
  in the FE and refreshes it in the background, so its first queries after a restart are fast.
- **One query at a time in Grafana.** The plugin runs an in-process DuckDB on one connection,
  so dashboard panels queue instead of running in parallel (a full load takes 3–9 s warm).
- **No background refresh.** `device_series` is a snapshot rebuilt by `duckdb-init`, while
  StarRocks refreshes its materialized view every 10 minutes.

For dashboards, `starrocks/` is the better fit; DuckDB suits ad-hoc and local analysis.

## Notes

- `SET GLOBAL s3_url_style = 'path'` is needed for bucket names with dots: virtual-hosted URLs fail
  TLS (`SSL peer certificate ... was not OK`). `GLOBAL`, because the plugin opens more than
  one connection and a plain `SET` only applies to the first.
- The plugin has no `$HOME`; the init SQL sets `home_directory` and installs `avro` before
  `iceberg`, which would otherwise fail to auto-install it.
