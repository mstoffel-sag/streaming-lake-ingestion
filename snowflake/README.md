# Snowflake

Query the Cumulocity Iceberg tables from Snowflake through a catalog-linked database on the
Polaris REST catalog, publish a subset as a data product to SAP Business Data Cloud (BDC), and
chart the measurements in Grafana. Data stays in Cumulocity storage; Snowflake reads it with
credentials vended by Polaris.

```
Snowflake (SAP Snowflake account in the BDC formation)
    ├── CUMULOCITY_BDC_<T>      data product: ALARM, INVENTORY, one table per fragment (dynamic Iceberg V3)
    │       └── share ──► Zerocopy Connector ──► SAP BDC catalog
    ├── CUMULOCITY_<T>          CURATED (dynamic tables, series view), OPS (procedures, task graph, alert)
    └── CUMULOCITY_ICEBERG_<T>  catalog-linked, read-only
            └── Polaris REST Catalog  (OAuth2 client credentials)
                    └── S3  (vended credentials)
```

## Notebooks

Import them into Snowsight (Projects → Notebooks → Import .ipynb). They use `%%sql` cells and
the Snowpark session, so they run as Snowflake Notebooks, not in a local Jupyter.

| Notebook | Purpose |
|---|---|
| `cumulocity_build_up.ipynb` | Creates everything for one tenant: warehouse, catalog integration, linked database, curated dynamic tables, measurement series view, schema-change task, optional e-mail alert |
| `sap-bdc/cumulocity_bdc_data_product.ipynb` | Publishes alarms, inventory and sewage pump measurements as a data product to SAP BDC and republishes it on schema changes (see below) |
| `cumulocity_query_examples.ipynb` | Read-only queries: devices, alarms, measurements, events, device timeline |
| `cumulocity_tear_down.ipynb` | Removes all objects of one tenant, the data product included (irreversible) |
| `grafana/` | Grafana stack on `CURATED` (see below) |

All object names end with the tenant ID, so several tenants can share one account.

## Prerequisites

- Snowflake account with `ACCOUNTADMIN`
- Polaris catalog principal (OAuth2 client credentials), see
  [Obtaining Iceberg catalog credentials](https://cumulocity.com/docs/datahub/streaming-lake-ingestion/#obtaining-iceberg-catalog-credentials)
- For alerting: a verified e-mail of a user in the account
- For the data product: an SAP Snowflake account (or a Snowflake account connected through SAP BDC
  Connect for Snowflake) that is part of a BDC formation; not available on trial accounts

## Usage

1. In `cumulocity_build_up.ipynb`, set `catalog_host`, `catalog_name` (tenant ID),
   `oauth_client_id`, `oauth_client_secret` and optionally `alert_email`, then run top to bottom.
2. Re-run the sync cells in section 3 until the CDC tables show snapshots.
3. Query `CUMULOCITY_<T>.CURATED.*` and `CUMULOCITY_ICEBERG_<T>."cdc_measurement"."<series>"`.

The OAuth secret is stored in plain text in the notebook (a catalog integration only accepts a
literal secret). Clear it before exporting or committing the notebook.

`CURATED.SERIES_VALUES` is a view with every measurement series in long format (`TIME` in UTC,
`DEVICE_ID`, `FRAGMENT`, `SERIES`, `VALUE`, `UNIT`, `MEASUREMENT_ID`): one `UNION ALL` branch per
series, so a filter on `SERIES` or `FRAGMENT` reads only the matching tables.
`CURATED.DEVICE_SERIES` lists every device and series with its unit, count and time range.

## SAP BDC data product

`sap-bdc/cumulocity_bdc_data_product.ipynb` publishes the same content as the Databricks data product
(`databricks/sap-bdc/bdc_connect.py`) through the native SAP Snowflake mechanism: a Snowflake share
associated with the BDC Zerocopy Connector, ORD metadata and a CSN schema passed to
`SYSTEM$SAP_PUBLISH_DATA_PRODUCT`.

| Table in `CUMULOCITY_BDC_<T>.CUMULOCITY` | Source | One row per | Key |
|---|---|---|---|
| `ALARM` | `cdc_alarm."alarm"` | alarm, current state | `ID` |
| `INVENTORY` | `cdc_inventory."inventory"` | managed object, current state (deleted ones excluded) | `ID` |
| `SEWPUMP_<FRAGMENT>`, for example `SEWPUMP_WINDINGTEMPC` | one per `cdc_measurement."c8y_SewPump_*"` table (19) | measurement | `ID` |

The measurement tables keep the lake layout, as in the Databricks product: one table per fragment,
one column per series. The table name is the source name without `c8y_`, in upper case. The series
object becomes the value as `DOUBLE` under the series name (`WINDING_TEMP_C`) and its unit
(`WINDING_TEMP_C_UNIT`). Join `SOURCE` of the measurement and alarm tables to `INVENTORY.ID`. Column
names are `UPPER_SNAKE_CASE`, timestamps UTC, arrays and objects in `ALARM` and `INVENTORY` JSON
text. Difference from the Databricks product: `ALARM` holds the current state per alarm, not the
change log.

### 1. In Snowflake and BDC

BDC accepts only Snowflake-managed Iceberg V3 tables (copy-on-write, `COMPATIBLE` serialization)
with a primary key, one database per data product. The notebook creates them as dynamic Iceberg
tables that refresh at most `target_lag` (10 minutes) behind the source.

1. Run `cumulocity_build_up.ipynb` for the tenant.
2. Check the connector: `SHOW ZEROCOPY CONNECTORS IN ACCOUNT`. SAP creates
   `CONNECTORS.ZEROCOPY.DEFAULT_SAP_BDC_CONNECTOR` when the SAP Snowflake system joins the
   formation; its status must be `CONNECTED`.
3. In `sap-bdc/cumulocity_bdc_data_product.ipynb`, set `catalog_name`, `share_name` and the ORD texts, then
   run sections 1 to 4. They create the database, the share and the tables, and change nothing in BDC.
   `bdc_csn_preview` shows the CSN document.
4. Run section 5. It enables share-back on the connector, adds the share and publishes. BDC extracts
   the metadata within a few minutes (*Catalog & Marketplace → Metadata Extractions →
   snowflake-…*); then the data product is in the catalog with lifecycle and release status Active.
5. Run section 6 (task graph) and section 7 (checks).

### 2. Republish on schema change

The Snowflake counterpart of the Databricks `bdc_check` → `bdc_changed` → `bdc_publish` tasks is a
task graph below the existing schema-change task. All tasks are serverless.

| Task | Runs | Does |
|---|---|---|
| `OPS.REBUILD_ON_SCHEMA_CHANGE` | every 15 min (root) | Rebuilds `CURATED` when source columns change |
| `OPS.BDC_CHECK` | after the root | Rebuilds the shared tables when the columns of alarm, inventory or the `c8y_SewPump_*` tables change. Compares an MD5 fingerprint of the shared schema (table, column, type, precision, scale, nullability) with the last publish and returns `changed` or `unchanged` |
| `OPS.BDC_PUBLISH` | after `BDC_CHECK`, `WHEN` it returned `changed` | Generates the CSN, publishes, stores the fingerprint in `OPS.BDC_STATE` |

A new inventory column or sewage pump fragment changes the CSN: the check rebuilds the tables (a new
fragment gets its own table, a removed one is dropped) and the product is republished within one
cycle. To force a
republish, run `CALL CUMULOCITY_<T>.OPS.BDC_PUBLISH()`. BDC accepts a republish under the same
version 1.0.0.

`BDC_CHECK` and `BDC_PUBLISH` run with caller's rights: `SYSTEM$SAP_PUBLISH_DATA_PRODUCT` and
`SYSTEM$SET_RETURN_VALUE` are refused inside owner's-rights procedures.

### 3. Consuming the data product

Installation targets come from the formation's request cart (*Add to Cart → Select Target
System*). In the BDC ExperienceCenter EU10 formation (checked 2026-10-29) the cart offers only
`databricks-6918e1f0` and `snowflake-7df47c68`:

| Data product from | SAP Databricks | SAP Snowflake | SAP Datasphere |
|---|---|---|---|
| SAP Snowflake (this one) | supported | no (same system) | not offered |
| SAP Databricks | no (same system) | no: "Data products from Databricks systems can't be installed to Snowflake systems" | not offered |

So the Snowflake product can be installed to SAP Databricks, which the Databricks product cannot
reach anywhere. Neither reaches Datasphere: the formation doesn't list `datasphere-tenant-ccf8cb77`
as a target at all, and *Metadata Extractions* shows it as *External SAP Datasphere* with a *Missing
User* warning. Making Datasphere a target needs a Datasphere and BDC administrator.

## Grafana

`grafana/` runs Grafana locally against the `CURATED` schema with the community
[Snowflake data source by Michelin](https://github.com/michelin/snowflake-grafana-datasource)
(Grafana's own Snowflake plugin needs Enterprise or Cloud). Grafana signs in as a service user with
a key pair and shows the **Cumulocity / Measurements (Snowflake)** dashboard: pick a device, then one
or more of its measurement series.

```
Grafana (localhost:GRAFANA_PORT)  [michelin-snowflake-datasource]
    └── CUMULOCITY_WH_<T>  (service user GRAFANA_CUMULOCITY, key pair)
            └── CURATED.SERIES_VALUES / CURATED.DEVICE_SERIES  →  cdc_measurement Iceberg tables
```

`cumulocity_build_up.ipynb` must have run for the tenant. Creating the user needs `ACCOUNTADMIN`.

### 1. In Snowflake

1. **Key pair.** From `grafana/`:
   ```bash
   mkdir -p secrets && openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -out secrets/grafana_key.p8
   ```
   ```bash
   openssl rsa -in secrets/grafana_key.p8 -pubout -out secrets/grafana_key.pub
   ```
   The plugin passes the key to the Snowflake Go driver, which expects base64url-encoded DER:
   ```bash
   openssl pkcs8 -topk8 -nocrypt -in secrets/grafana_key.p8 -outform DER | base64 | tr -d '\n' | tr '+/' '-_' > secrets/grafana_key.b64
   ```
   `secrets/` is in `.gitignore`.
2. **Role and user.** In a worksheet, run `grafana/setup.sql` with your tenant ID and the public key
   (the lines between `BEGIN` and `END` of `grafana_key.pub`, joined). It creates the role
   `GRAFANA_CUMULOCITY_READER` (warehouse usage, `SELECT` on `CURATED`, future objects included) and
   the service user `GRAFANA_CUMULOCITY` (`TYPE = SERVICE`, key pair only).

### 2. Start Grafana locally

```bash
cd grafana
cp .env.example .env    # check account, user, role, warehouse, database; set an admin password and port
docker compose up -d --build
```

The compose project is called `grafana-snowflake`, so it doesn't replace the `databricks/grafana`
containers (same folder name). The StarRocks, Doris and DuckDB stacks use port 3000 and
`databricks/grafana` often 3001; set `GRAFANA_PORT=3002` to run next to them. Grafana logs a
warning that the plugin is unsigned, which is expected.

### 3. Open the dashboard

Open **http://localhost:3002** (or your `GRAFANA_PORT`) and sign in as `admin` with
`GRAFANA_ADMIN_PASSWORD` from `.env`. The dashboard is the home page (also under *Dashboards →
Cumulocity*).

- **Device**: all devices with measurements, as `name · id`.
- **Series**: the selected device's series; starts with the first one, add more as needed.
- Panels: the selected series in one chart, latest / min / avg / max per series, the latest 200
  values, all series of the device, and one chart per series below.
- Default range is the last 6 hours. There is no auto-refresh; use *Refresh* or pick 15m or longer.

### Notes

- The first query after the warehouse suspended (60 s idle) waits for it to resume, a few seconds.
- The time series queries use the plugin without fill mode: its fill mode inserts empty rows that
  break the long-to-wide conversion and show up as an extra series.
- `CURATED.DEVICE_SERIES` refreshes every 15 minutes; new devices and series appear in the lists
  after that.

## Notes

- `latest_inventory` tables can't be read in Snowflake (Iceberg equality deletes are
  unsupported); `DEVICE_LATEST`, `ALARM_LATEST` and the shared `INVENTORY` and `ALARM` are
  derived from the CDC logs instead and refresh incrementally.
- A serverless task checks every 15 min for column changes in `cdc_inventory`, `cdc_alarm` and
  `cdc_measurement` and rebuilds the dynamic tables and the series view when the schema evolves.
- Every dynamic-table refresh resumes the tenant warehouse (60 s minimum billing). Raise
  `TARGET_LAG` in the notebooks to lower the cost.
