# Databricks

Incrementally import Cumulocity Iceberg tables from the Polaris catalog into Delta tables.
The catalog vends S3 credentials, so no AWS keys are stored.

| File | Purpose |
|---|---|
| `Edit_Secrets.py` | Creates and edits the `CumulocityPolarisIcebergS3` secret scope (Polaris OAuth client, token URL, scope, base URL, warehouse; `aws_region` optional) |
| `IcebergIncrementalImport PyIceberg.ipynb` | Import via PyIceberg scans (**recommended**) |
| `IcebergIncrementalImport DuckDB.ipynb` | Import via DuckDB `read_parquet` on new data files |
| `grafana/` | Grafana stack on the SQL warehouse: measurement views, lookup refresh notebook, dashboard (see below) |
| `sap-bdc/bdc_connect.py` | Creates a Delta Share from selected import tables and publishes it as a data product to SAP Business Data Cloud (consumable in SAP Datasphere) |
| `sap-bdc/bdc_tables.py` | Table selection and schema fingerprint of the data product (a workspace file imported by the two notebooks) |
| `sap-bdc/CheckBdcSchema.py` | Decides whether the data product needs a republish (see below) |
| `sap-bdc/RefreshMeasurementFact.py` | Rebuilds `curated_measurement`, all measurement series in long format |
| `sap-bdc/bdc_delete.py` | Removes the data product from BDC and drops the Delta Share |

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
3. **Flatten** nested columns: one level of objects becomes columns, lists and deeper objects become JSON
   strings (no `struct` columns), and a unique `row_id` is added.
4. **Write** to Delta (append with `mergeSchema`, or overwrite), store snapshot ID and sequence number.
5. Ensure `PRIMARY KEY (row_id)` on every target table. The run fails if any table failed to import.

## PyIceberg vs. DuckDB

- **PyIceberg** applies Iceberg delete files, so updated or deleted source rows are handled
  correctly. PyIceberg itself can't plan scans with equality deletes; the notebook builds the
  scan tasks and applies equality deletes by sequence number (table-wide, not per partition).
- **DuckDB** always reads new data files directly and ignores delete files. Faster for large
  append-only tables, but can re-import deleted or superseded rows. Use it only for append-only data.

## SAP BDC data product

`bdc_connect` shares everything the import writes for the tenant in the Delta Share `cumulocity_adhoc_demo`,
grants it to the recipient `sap-business-data-cloud`, and publishes it to SAP Business Data Cloud with
ORD metadata and a CSN schema generated from the tables:

| In the share | Source | Content |
|---|---|---|
| `cdc_<namespace>.<table>` | every `cdc_*` table | Change log per Iceberg table: alarms, events, inventory, one table per measurement fragment |
| `latest_<namespace>.<table>` | every `latest_*` table | Current state per object (inventory) |
| `curated.measurement` | `curated_measurement` | Every measurement series in long format: `id, fragment, series, time, source, value, unit`, key `(id, fragment, series)`. The fact for analytic models |

New Iceberg tables join automatically (`bdc_tables.share_tables`); helper tables (`_*`, `grafana_*`,
`internal_*`) are left out. The task `measurement_fact` rebuilds `curated_measurement` after every import
(`RefreshMeasurementFact`); it discovers the `<series>_value` columns on each run.

Two adjustments make the tables installable in Datasphere: the CSN declares timestamps as `cds.Timestamp`
(the SDK generates `cds.DateTime`, which Datasphere rejects with `MISMATCH IN DATA TYPE`), and the import
writes no `struct` columns, which the CSN can't express. It needs `CREATE SHARE` and `USE RECIPIENT` on
the metastore (granted by the BDC operators) and the `sap-bdc-connect-sdk` secret scope with `api_url`,
`tenant` and `token_audience`.

**Republish on schema change.** Three tasks in the import job keep the data product in step with the
tables:

| Task | Does |
|---|---|
| `bdc_check` | After a successful import, computes a SHA-256 fingerprint over the selected tables, their names in the share, columns, types and nullability, and compares it with the last publish (`_bdc_publish_state`). Sets the task value `changed`. Takes seconds, installs nothing. |
| `bdc_changed` | Condition: `{{tasks.bdc_check.values.changed}} == "true"`. |
| `bdc_publish` | Runs `bdc_connect` (share contents, ORD, CSN, publish) and stores the new fingerprint. |

So a new measurement column (the import appends with `mergeSchema`), a changed type, or a new Iceberg
table republishes the data product within one import cycle; otherwise nothing runs. To
force a republish, delete the share's rows from `_bdc_publish_state` or run `bdc_connect` by hand.
Import the notebooks from `sap-bdc/` into the workspace and upload `bdc_tables.py` as a workspace file next to them.

`bdc_connect` also removes share tables whose source table no longer matches the selection, which
removes them from the data product; consumers in Datasphere that use them break.

### Step by step: from Databricks to Datasphere

**Once, by the platform admins**
- Databricks metastore: `CREATE SHARE` for you (workspace admins have it) and `USE RECIPIENT` on
  `sap-business-data-cloud` (only the BDC operators can grant it).
- Secret scope `sap-bdc-connect-sdk` with `api_url`, `tenant` and `token_audience`.
- Datasphere: a space for the data (here `CUMULOCITY`) with you as a member who may install data products,
  and Datasphere enabled as a target for data products from the SAP Databricks system.
- BDC: the approver role for the domain (*Governance → Access Management* shows the requests).

**1. Databricks: publish**
1. Import `sap-bdc/` into the workspace folder of the import notebook: `bdc_connect`, `CheckBdcSchema`,
   `RefreshMeasurementFact`, `bdc_delete` as notebooks, `bdc_tables.py` as a file.
2. Import job: add the task `measurement_fact` (notebook `RefreshMeasurementFact`, depends on `import`,
   *Run if* **All done**) and run the job once, so `curated_measurement` exists.
3. Decide the table names now: renaming or removing tables after the first install is a breaking change (see
   below).
4. Run `bdc_connect`. The output lists every table (`source -> schema.table`), then `Share registered.`,
   `CSN uploaded.` and `Data product '...' published`.
5. Optional, automatic republish: add the tasks `bdc_check`, `bdc_changed` and `bdc_publish` (table above).

**2. BDC: wait for the catalog**
1. BDC cockpit, *Catalog & Marketplace → Metadata Extractions*: wait until `databricks-6918e1f0` shows
   *Synchronized* with *Last Synchronized* **after** your publish. The catalog shows what the last extraction
   read, not what you just published.
2. *Catalog & Marketplace → Search → Data Products*: open the product and check version, description and
   *APIs* (functional status *Current*).

**3. Datasphere: request, approve, install**
1. In **Datasphere** (not the BDC cockpit, whose cart doesn't offer Datasphere): *Catalog & Marketplace →
   Search → Data Products*, find the product, *Add to Cart*, open the cart, *Proceed*.
2. *Request Access*: space `CUMULOCITY`, a comment, no end date, accept the terms, *Send*.
3. BDC cockpit, *Governance → Access Management*: open the request and *Approve*.
4. Datasphere, *Catalog & Marketplace → Data Product Access → Agreements*: open the agreement (status
   *Current*), *Install Data Product*, delivery method **Federation** (queries read the Delta tables live;
   Replication copies them), *Install*.
5. Watch the notifications (bell): *Data Product Installation: Completed* with *Saved objects* equal to
   *Deployed objects*. With *Failed*, *Show More* lists the table and column; deployment is all or nothing.
6. *Data Builder →* space `CUMULOCITY`: every table is a *Remote Table*, status *Deployed*. Open one,
   *Data Viewer*, and compare the row count with Databricks.

**Changing the data product later**
- Additive changes (new tables or columns) need a republish (automatic with the `bdc_*` tasks), a catalog
  sync, then *Check for Schema Changes* or *⋯ → Reinstall Data Product* on the agreement.
- Renaming or removing tables broke the installed product here: BDC kept serving the old definition after the
  republish, and the reinstall deployed the old tables, which no longer existed in the share. For such a
  change, publish a new major version instead (`ordId` `...:v2`, `version` `2.0.0`) and install that.

**Removing everything**
1. Remove the `bdc_*` tasks from the import job, or the next schema change publishes again.
2. Datasphere, *Data Product Access → Agreements →* the agreement *→ End Agreement* (uninstalls it).
3. Run `bdc_delete`: deletes the share and data product in BDC, then drops the Delta Share and
   `_bdc_publish_state`. The catalog entry disappears with the next metadata extraction.

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
