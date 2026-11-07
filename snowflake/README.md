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
| `sap-bdc/cumulocity_bdc_data_product.ipynb` | Publishes alarms, events, operations, inventory and all measurements as a data product to SAP BDC and republishes it on schema changes (see below) |
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
| `INVENTORY_<FRAGMENT>`, for example `INVENTORY_AGENT` | one per other `cdc_inventory` table (`c8y_Agent`) | managed object with that fragment, current state | `ID` (= `INVENTORY.ID`) |
| `EVENT` | `cdc_event."event"` | event | `ID` |
| `EVENT_<FRAGMENT>`, for example `EVENT_WORKORDER` | one per other `cdc_event` table (`c8y_WorkOrder`) | event with that fragment | `ID` (= `EVENT.ID`) |
| `OPERATION` | `cdc_operation."operation"` | operation, current state | `ID` |
| `<FRAGMENT>`, for example `SEWPUMP_WINDINGTEMPC`, `AERLANE_HEALTH` | one per `cdc_measurement` table matching `measurement_tables` (default `%`, all) | measurement | `ID` |

New tables in these Iceberg namespaces join automatically. Not shared: `cdc_rejected` (payloads the
ingestion rejected), `internal` (ingestion state) and the `latest_*` tables, which Snowflake can't
read ("Equality deletes on Iceberg tables are not supported"); `INVENTORY_*` carries the same current
state, built from the change log.

The measurement tables keep the lake layout, as in the Databricks product: one table per fragment,
one column per series. The table name is the source name without `c8y_`, in upper case. The series
object becomes the value as `DOUBLE` under the series name (`WINDING_TEMP_C`) and its unit
(`WINDING_TEMP_C_UNIT`). Join `SOURCE` of the measurement, event and alarm tables to `INVENTORY.ID`.
Column names are `UPPER_SNAKE_CASE`, timestamps UTC, arrays and objects outside the measurement tables
JSON text. Repeated underscores in column names collapse to one (`c8y_Context.id__0` becomes
`ID_0`): with an element `ID__0` in the CSN, the publish succeeded but the BDC metadata extraction
failed with "missing required property (dataProduct-entities)" (2026-11-06). All tables sit in one schema, and Datasphere names them `<share>:v1.<TABLE>`, so the build
procedure stops when two sources map to the same name. Difference from the Databricks product: the
change logs of alarms, inventory, events and operations are reduced to the current state per `ID`;
rows whose latest change is a delete are left out. The latest row is the one with the newest
`lastUpdated`, then the newest other timestamp column of the table: Cumulocity updates
`c8y_Availability.lastMessage` without changing `lastUpdated`, so one device had 381 change rows with
the same `lastUpdated` (2026-11-07). Without the second key, `INVENTORY_AVAILABILITY` returned an
arbitrary one of them. `c8y_ActiveAlarmsStatus` has the same ties (34 of 35 managed objects) and no
other timestamp, and Snowflake exposes no write order for Iceberg rows. So
`INVENTORY_ACTIVEALARMSSTATUS` doesn't read the counters from the change log. It counts the
uncleared (`ACTIVE`, `ACKNOWLEDGED`) alarms per severity from the alarm change log, for every managed
object that has the fragment; `LAST_UPDATED` is the newest change of the fragment or of one of the
object's alarms. Checked against Cumulocity on 2026-11-07 15:01 UTC: 33 of 39 objects with the
fragment matched; 2 had an alarm raised or cleared after the newest alarm in the lake (14:59), and 4
last changed before the ingestion started, so the lake has no row for them (one of these, 723200,
shows a warning in the fragment without any open alarm). The counts are `NUMBER(38,0)`, and the CSN
declares all numbers as `cds.Decimal(p, s)`. The publish rejected `cds.Integer64` for the
`NUMBER(13,0)` that `COUNT_IF` returns ("does not match the provider type [decimal(13, 0)]"); with
`NUMBER(19,0)` the publish passed, but the Datasphere reinstall failed twice with "MISMATCH IN DATA
TYPE PRECISION" (input 19, actual 38). A reinstall 3 minutes after the `NUMBER(38,0)` publish (and 2
minutes after BDC extracted it) still imported the precision-19 definition: Datasphere's copy of the
CSN lags behind BDC. While a reinstall fails, the tables installed before stay as they were.

Every shared table is a dynamic table that refreshes within `target_lag` on the tenant's warehouse;
with all measurement fragments that is over 100 tables. Raise `target_lag` or narrow
`measurement_tables` (for example `c8y_SewPump%`) if warehouse credits matter more than freshness.

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
| `OPS.BDC_CHECK` | after the root | Rebuilds the shared tables when the columns of any alarm, inventory, event, operation or selected measurement table change. Compares an MD5 fingerprint of the shared schema (table, column, type, precision, scale, nullability) with the last publish and returns `changed` or `unchanged` |
| `OPS.BDC_PUBLISH` | after `BDC_CHECK`, `WHEN` it returned `changed` | Generates the CSN, publishes, stores the fingerprint in `OPS.BDC_STATE` |

A new inventory column, event type or measurement fragment changes the CSN: the check runs
`BDC_CREATE_TABLES` (a new fragment gets its own table, a removed one is dropped) and the product is
republished within one cycle. `BDC_CREATE_TABLES` replaces only tables whose definition changed: each
table's comment ends with an MD5 tag of its properties and `SELECT`, and tables with the current tag
are left alone. Replacing all tables would make every table new on the SAP side (see the reinstall
delay below). To force a
republish, run `CALL CUMULOCITY_<T>.OPS.BDC_PUBLISH()`. BDC accepts a republish under the same
version 1.0.0.

`BDC_CHECK` and `BDC_PUBLISH` run with caller's rights: `SYSTEM$SAP_PUBLISH_DATA_PRODUCT` and
`SYSTEM$SET_RETURN_VALUE` are refused inside owner's-rights procedures.

### 3. Consuming the data product

Where you can install the data product depends on where you request it. The BDC cockpit's request
cart (*Add to Cart → Select Target System*) offers only the SAP Databricks and SAP Snowflake systems
of the formation. Datasphere's own catalog requests access for Datasphere itself (checked 2026-11-06,
BDC ExperienceCenter EU10):

| Data product from | SAP Databricks | SAP Snowflake | SAP Datasphere |
|---|---|---|---|
| SAP Snowflake (this one) | supported (BDC cockpit cart) | no (same system) | supported (request in Datasphere) |
| SAP Databricks | no (same system) | no: "Data products from Databricks systems can't be installed to Snowflake systems" | supported (request in Datasphere) |

The CSN is already Datasphere-compatible: timestamps are `cds.Timestamp`, there are no structured
columns (arrays and objects are JSON text), and all tables sit in one schema, so the remote table
names `<share>:v1.<TABLE>` can't collide. `SYSTEM$SAP_PUBLISH_DATA_PRODUCT` checks the CSN against the
share: every shared table and column must be in it, with the same names.

**Install in Datasphere** (same steps as for the Databricks product, see
[../databricks/sap-bdc/README.md](../databricks/sap-bdc/README.md)):

1. Wait until *Catalog & Marketplace → Metadata Extractions* in the BDC cockpit shows
   `snowflake-7df47c68` *Synchronized* with a time after the publish.
2. In **Datasphere**, *Catalog & Marketplace → Search → Data Products*, find the product (source system
   `snowflake-…`), *Add to Cart*, open the cart, *Proceed*.
3. *Request Access*: space `CUMULOCITY`, a comment, no end date, accept the terms, *Send*.
4. BDC cockpit, *Governance → Access Management → Requests*: open the request, *Approve*.
5. Datasphere, *Catalog & Marketplace → Data Product Access → Agreements*: open the agreement,
   *Install Data Product*, delivery method **Federation** (the default is Replication), *Install*.
6. Watch the notifications (bell, reload the page): *Data Product Installation: Completed* with
   *Saved objects* equal to *Deployed objects*.
7. *Data Builder →* space `CUMULOCITY`: the tables appear as remote tables of the SAP-managed space
   `SNOWFLAKE7DF47C68`, shared into `CUMULOCITY`, named `cumulocity_adhoc_demo:v1.<TABLE>`. They can't
   be opened from there; to check the data, open *New SQL View*, query
   `"SNOWFLAKE7DF47C68.cumulocity_adhoc_demo:v1.SEWPUMP_WINDINGTEMPC"`, use *Data Viewer*, and discard
   the view.

Tested 2026-11-06: the install with Federation took about 7 minutes and deployed all 21 tables
(`ALARM`, `INVENTORY`, 19 `SEWPUMP_*`) with no type errors. `SEWPUMP_WINDINGTEMPC` returned 207,856 rows
in Datasphere.

**After adding or replacing tables, wait before reinstalling.** On 2026-11-06 the product grew to 119
tables and BDC extracted them, but *Reinstall Data Product* about 75 minutes after the publish failed:
119 objects saved, 0 deployed, "Remote object 'cumulocity_adhoc_demoCUMULOCITY<TABLE>' in connection
'DWC_SNOWFLAKE7DF47C68.SNOWFLAKE7DF47C68' could not be found" for the new tables. The installed tables
kept returning a snapshot from before the change (`SEWPUMP_WINDINGTEMPC`: 207,856 rows up to 15:39 UTC,
while Snowflake had 209,458 rows up to 18:06), even an hour later. The SAP side picks up tables that
`BDC_CREATE_TABLES` adds or replaces (`CREATE OR REPLACE`) only after a delay; the same reinstall the
next morning (2026-11-07) deployed 119 of 119 in 8 minutes, and Datasphere then matched Snowflake
within the dynamic tables' lag (`SEWPUMP_WINDINGTEMPC`: 219,351 rows up to 09:14 UTC in Datasphere,
219,422 up to 09:21 in Snowflake at 09:27). If a reinstall reports "could not be found", wait and
retry; check the freshness of an installed table first.

**A new measurement fragment end to end** (2026-11-07, three `c8y_BdcFlowTest` measurements with the
series `TempC` on device 9682000, times UTC):

| Time | Step |
|---|---|
| 13:18:09–13:18:19 | Measurements created in Cumulocity |
| 13:20:09 | Iceberg table `cdc_measurement."c8y_BdcFlowTest"` created |
| 13:22:16 | `REBUILD_ON_SCHEMA_CHANGE` starts (15-minute schedule) |
| 13:23:50 | `BDC_CHECK` creates `BDCFLOWTEST`; the other 119 tables stay untouched |
| 13:24:55 | `BDC_PUBLISH` succeeds |
| 13:25:50 | BDC metadata extraction `snowflake-7df47c68` *Synchronized*, 0 errors |
| 13:35 | Datasphere: *Check for Schema Changes* reports "Up to Date" (it doesn't add new tables); *Reinstall Data Product*, Federation |
| 13:41 | Reinstall completed: 120 saved, 120 deployed |
| 13:45 | `"SNOWFLAKE7DF47C68.cumulocity_adhoc_demo:v1.BDCFLOWTEST"` returns the 3 rows (`TEMP_C` 21.5, 22, 22.5, unit `C`) |

From measurement to the published product took under 7 minutes; the rest is the manual reinstall.
Here the reinstall worked 10 minutes after the publish, unlike the failed one on 2026-11-06, which
came 75 minutes after a publish that added 98 tables and replaced 21. The 4 tables replaced at
10:21 the same day (`ALARM`, `EVENT`, `INVENTORY`, `INVENTORY_AVAILABILITY`) were also current in
Datasphere after this reinstall (`INVENTORY_AVAILABILITY.LAST_MESSAGE` 13:29 at 13:46).

After `OPS.BDC_PUBLISH` republishes a schema change, the Datasphere side stays manual, as for
Databricks: *Data Product Access → Agreements →* the agreement *→ Check for Schema Changes* or
*Reinstall Data Product*. Remove the installation with *End Agreement* before the tear-down notebook
drops the share.

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
