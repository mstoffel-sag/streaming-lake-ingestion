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
Databricks plugin needs Enterprise or Cloud). Grafana signs in as a service principal (OAuth M2M)
and shows the **Cumulocity / Measurements (Databricks)** dashboard: pick a device, then one or more
of its measurement series.

```
Grafana (localhost:GRAFANA_PORT)  [mullerpeter-databricks-datasource]
    └── SQL warehouse  (OAuth M2M as a service principal)
            └── grafana_series_values / grafana_device_series  →  cdc_measurement_* Delta tables
```

The import job must already be running (see Setup above). Creating the service principal and its
secret needs a workspace admin.

### 1. In Databricks

1. **Service principal.** *Settings → Identity and access → Service principals → Add service
   principal → Add new* (e.g. `grafana-cumulocity`). Keep the *Databricks SQL access* entitlement.
   Note its **Application ID**.
2. **OAuth secret.** Open the service principal → *Secrets* → *Generate secret*. Copy the secret
   right away; it is shown only once.
3. **Read access.** In the SQL editor (`<application id>` in backticks):
   ```sql
   GRANT USE CATALOG ON CATALOG factory TO `<application id>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA factory.`adhoc-demo_eu-latest-t2180777119` TO `<application id>`;
   ```
4. **Warehouse.** *SQL Warehouses →* your warehouse *→ Permissions →* add the service principal with
   **Can use**. On the *Connection details* tab, note **Server hostname** and **HTTP path**.
5. **Views for the dashboard.** From this folder, with a Databricks CLI profile that may create
   views in the schema (`databricks auth login --host https://<workspace host> --profile c8y-lake`):
   ```bash
   python3 grafana/series_views.py --profile c8y-lake --warehouse <warehouse id>
   ```
   This creates `grafana_series_values` (every series in one long view; `metric` is the series
   name), the view `grafana_device_series_v` and the table `grafana_device_series` materialized from
   it (device and series lists). Re-run it when new measurement types or series appear; new devices
   and values are picked up automatically.
6. **Keep the lists current.** Import `grafana/RefreshGrafanaLookup.py` into the workspace (*Workspace
   → Import*, next to the import notebook). In the import job, *Add task → Notebook*: that notebook,
   *Depends on* `import`, *Run if* **All done**. It rebuilds `grafana_device_series` after every import
   (~30 s on serverless; materialized views would need Pipelines, which this workspace lacks).

### 2. Start Grafana locally

```bash
cd grafana
cp .env.example .env    # fill in hostname, HTTP path, application ID, secret, an admin password
docker compose up -d --build
```

`GRAFANA_PORT` in `.env` sets the port (default 3000; the StarRocks, Doris and DuckDB stacks use
3000 too). The image adds the plugin from its GitHub release; Grafana logs a warning that the plugin
is unsigned, which is expected.

### 3. Open the dashboard

Open **http://localhost:3000** (or your `GRAFANA_PORT`) and sign in as `admin` with
`GRAFANA_ADMIN_PASSWORD` from `.env`. The dashboard is the home page (also under *Dashboards →
Cumulocity*).

- **Device**: all devices with measurements, as `name · id`.
- **Series**: the selected device's series; starts with the first one, add more as needed. Each
  series costs one table scan per panel, so pick only what you need.
- Panels: the selected series in one chart, latest / min / avg / max per series, the latest 200
  values, all series of the device, and one chart per series below (for series whose scales differ).
- Default range is the last 6 hours. There is no auto-refresh; use *Refresh* or pick 15m or longer.

### Notes

- The warehouse auto-stops after 10 idle minutes. The first query after a stop waits for it to start
  (≈20 s); after that panels take ≈4 s. Refreshing more often than every 10 minutes keeps it running.
- `$__timeFilter` is rendered as UTC literals, matching the warehouse's UTC session time zone.
- In this workspace `account users` holds ALL PRIVILEGES on the `factory` catalog, so every account
  principal, the Grafana one included, can also write and drop objects there. Keep the secret local.

Clear notebook outputs before committing.
