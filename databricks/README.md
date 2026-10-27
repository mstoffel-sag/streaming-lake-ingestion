# Databricks

Incrementally import Cumulocity Iceberg tables from the Polaris catalog into Delta tables.
The catalog vends S3 credentials, so no AWS keys are stored.

| File | Purpose |
|---|---|
| `Edit_Secrets.py` | Creates and edits the `CumulocityPolarisIcebergS3` secret scope (Polaris OAuth client, token URL, scope, base URL, warehouse; `aws_region` optional) |
| `IcebergIncrementalImport PyIceberg.ipynb` | Import via PyIceberg scans (**recommended**) |
| `IcebergIncrementalImport DuckDB.ipynb` | Import via DuckDB `read_parquet` on new data files |
| `grafana/` | Grafana stack on the SQL warehouse: measurement views, lookup refresh notebook, dashboard (see below) |
| `bdc_connect.py` | Creates a Delta Share from selected import tables and publishes it as a data product to SAP Business Data Cloud (consumable in SAP Datasphere) |

## Setup

1. Run `Edit_Secrets.py` and fill in the Polaris values.
2. Run one of the import notebooks; schedule it as a job for continuous import.
   Set the `catalog` and `schema` parameters to choose where the Delta tables go
   (the schema is created if missing); leave them empty to use the compute's defaults.

## How the import works

Per table:
1. **Snapshot check:** if the Iceberg snapshot ID matches the last import (`_iceberg_snapshot_tracking`), skip the table.
2. **Choose the read:**
   - Table has delete files (upsert tables such as `latest_inventory.*`): read the whole table with
     position and equality deletes applied, then overwrite.
   - Only appends (or compactions) since the last imported snapshot: read just the data files those
     snapshots added, then append. Progress follows Iceberg snapshots, not event time, so late
     measurements and alarm updates are picked up.
   - Otherwise (first import, expired snapshot, overwrite/delete commits): full read, overwrite.
3. **Flatten** nested columns (lists/complex types become JSON), add a unique `row_id`.
4. **Write** to Delta (append with `mergeSchema`, or overwrite), store snapshot ID and sequence number.
5. Ensure `PRIMARY KEY (row_id)` on every target table. The run fails if any table failed to import.

## PyIceberg vs. DuckDB

- **PyIceberg** applies Iceberg delete files, so updated or deleted source rows are handled
  correctly. PyIceberg itself can't plan scans with equality deletes; the notebook builds the
  scan tasks and applies equality deletes by sequence number (table-wide, not per partition).
- **DuckDB** always reads new data files directly and ignores delete files. Faster for large
  append-only tables, but can re-import deleted or superseded rows. Use it only for append-only data.

## Grafana

`grafana/` runs Grafana locally against the Databricks SQL warehouse with the community
[Databricks data source](https://github.com/mullerpeter/databricks-grafana) (Grafana's own
Databricks plugin needs Enterprise or Cloud). It signs in as a service principal (OAuth M2M) and
provisions the **Cumulocity / Measurements (Databricks)** dashboard: pick a device, then one or more
series.

```
Grafana (port GRAFANA_PORT, default 3000)  [mullerpeter-databricks-datasource]
    └── SQL warehouse  (OAuth M2M, service principal)
            └── grafana_series_values / grafana_device_series  →  cdc_measurement_* Delta tables
```

Setup:
1. Service principal with an OAuth secret, and grants:
   ```sql
   GRANT USE CATALOG ON CATALOG factory TO `<application id>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA factory.`adhoc-demo_eu-latest-t2180777119` TO `<application id>`;
   ```
   plus **Can use** on the warehouse.
2. `python3 grafana/series_views.py` (uses the `c8y-lake` CLI profile; see `--help`). Creates
   `grafana_series_values` (all series, long format; `metric` is the series name), the view
   `grafana_device_series_v` and the table `grafana_device_series` materialized from it.
   Re-run when new measurement types or series appear.
3. Import `grafana/RefreshGrafanaLookup.py` as a notebook and add it to the import job as a task after
   the import (`run_if: ALL_DONE`); it rebuilds `grafana_device_series` (~30 s; materialized views
   would need Pipelines).
4. `cd grafana && cp .env.example .env` (fill in the client ID and secret), then `docker compose up -d --build`.

Notes:
- The warehouse auto-stops after 10 idle minutes; dashboard refreshes more frequent than that keep it
  running. The first query after a stop waits for the warehouse to start.
- Panels take ≈4–5 s warm (three series, 24 hours); the lookup lists ≈1 s.
- `$__timeFilter` is rendered as UTC literals, matching the warehouse's UTC session time zone.
- In this workspace `account users` holds ALL PRIVILEGES on the `factory` catalog, so every account
  principal, the Grafana one included, can also write and drop objects there. Keep the secret local.

Clear notebook outputs before committing.
