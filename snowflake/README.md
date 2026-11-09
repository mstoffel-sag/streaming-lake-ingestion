# Snowflake

Query the Cumulocity Iceberg tables from Snowflake through a catalog-linked database on the
Polaris REST catalog, publish a subset as a data product to SAP Business Data Cloud (BDC), and
chart the measurements in Grafana. Data stays in Cumulocity storage; Snowflake reads it with
credentials vended by Polaris.

```
Snowflake (SAP Snowflake account in the BDC formation)
    ├── CUMULOCITY_BDC_<T>      data product: alarms, events, operations, inventory, measurements (dynamic Iceberg V3)
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
| `sap-bdc/cumulocity_bdc_data_product.ipynb` | Publishes alarms, events, operations, inventory and all measurements as a data product to SAP BDC and republishes it on schema changes ([sap-bdc/README.md](sap-bdc/README.md)) |
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

`sap-bdc/cumulocity_bdc_data_product.ipynb` publishes the tenant's alarms, events, operations,
inventory and measurements as a data product to SAP Business Data Cloud and republishes it on schema
changes. Setup, tables, tasks, the Datasphere install and the steps from an Iceberg change to Datasphere:
[sap-bdc/README.md](sap-bdc/README.md).

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
