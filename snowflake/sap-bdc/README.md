# SAP BDC data product (Snowflake)

`cumulocity_bdc_data_product.ipynb` publishes the same content as the Databricks data product
(`databricks/sap-bdc/bdc_connect.py`) through the native SAP Snowflake mechanism: a Snowflake share
associated with the BDC Zerocopy Connector, ORD metadata and a CSN schema passed to
`SYSTEM$SAP_PUBLISH_DATA_PRODUCT`.

![Data flow of the Databricks and Snowflake data products into SAP Datasphere](../../sap-bdc-data-flow.png)

Data flow of both data products; editable source: [sap-bdc-data-flow.drawio](../../sap-bdc-data-flow.drawio).

| Table in `CUMULOCITY_BDC_<T>.CUMULOCITY` | Source | One row per | Key |
|---|---|---|---|
| `ALARM` | `cdc_alarm."alarm"` | alarm, current state | `ID` |
| `INVENTORY` | `cdc_inventory."inventory"` | managed object, current state (deleted ones excluded) | `ID` |
| `INVENTORY_<FRAGMENT>`, for example `INVENTORY_AGENT` | one per other `cdc_inventory` table (`c8y_Agent`) | managed object with that fragment, current state | `ID` (= `INVENTORY.ID`) |
| `EVENT` | `cdc_event."event"` | event | `ID` |
| `EVENT_<FRAGMENT>`, for example `EVENT_WORKORDER` | one per other `cdc_event` table (`c8y_WorkOrder`) | event with that fragment | `ID` (= `EVENT.ID`) |
| `OPERATION` | `cdc_operation."operation"` | operation, current state | `ID` |
| `<FRAGMENT>`, for example `SEWPUMP_WINDINGTEMPC`, `AERLANE_HEALTH` | one per `cdc_measurement` table matching `measurement_tables` (default `%`, all) | measurement | `ID` |
| `MEASUREMENT` | every series of the same `cdc_measurement` tables, long format | measurement and series | `ID`, `FRAGMENT`, `SERIES` |

New tables in these Iceberg namespaces join automatically. Not shared: `cdc_rejected` (payloads the
ingestion rejected), `internal` (ingestion state) and the `latest_*` tables, which Snowflake can't
read ("Equality deletes on Iceberg tables are not supported"); `INVENTORY_*` carries the same current
state, built from the change log.

The measurement tables keep the lake layout, as in the Databricks product: one table per fragment,
one column per series. The table name is the source name without `c8y_`, in upper case. The series
object becomes the value as `DOUBLE` under the series name (`WINDING_TEMP_C`) and its unit
(`WINDING_TEMP_C_UNIT`). Join `SOURCE` of the measurement, event and alarm tables to `INVENTORY.ID`.
`MEASUREMENT` holds the same values in long format, `ID, FRAGMENT, SERIES, TIME, SOURCE, VALUE, UNIT`,
with the source names (`FRAGMENT` = `c8y_SewPump_WindingTempC`, `SERIES` = `winding_temp_c`). It is
the fact for an Analytic Model in Datasphere and for SAP Analytics Cloud, which filter rows but can't
switch tables the way the Grafana dashboard does. The Databricks product has the same table as
`curated.curated_measurement`. A new fragment or series changes its query, so `BDC_CREATE_TABLES`
replaces `MEASUREMENT` together with adding the new table; until the SAP side picks up the replaced
table (see *Where it gets stuck* below), Datasphere may serve it stale.
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
shows a warning in the fragment without any open alarm). The counts keep the type of the source columns, `NUMBER(38,9)`, and the CSN declares all numbers as
`cds.Decimal(p, s)`.

**Keep the column types of an installed table.** A Datasphere reinstall can't change the type of a
column in a remote table it already installed. Changing the counts cost four attempts (2026-11-07 to
2026-11-09):

- `cds.Integer64` for the `NUMBER(13,0)` that `COUNT_IF` returns: the publish failed, "does not
  match the provider type [decimal(13, 0)]".
- `NUMBER(19,0)` as `cds.Decimal(19,0)`: published, but the reinstall failed twice with "MISMATCH IN
  DATA TYPE PRECISION" (input 19, actual 38).
- `NUMBER(38,0)`: "MISMATCH IN DATA TYPE SCALE" (input 0, actual 9). The "actual" type is the one
  installed first. A reinstall 2 minutes after BDC extracted this publish still imported precision
  19, so Datasphere's copy of the CSN also lags behind BDC.
- `NUMBER(38,9)`, the original type: published 2026-11-09 at 09:34 UTC. A reinstall 6 minutes later
  still imported scale 0, the definition published two days before. The reinstall at 11:29 UTC, two
  hours after the publish, completed in 9 minutes, and Datasphere served the alarm-based counts.
  Retry the reinstall a few hours after such a publish.

While a reinstall fails, the tables installed before stay as they were.

Every shared table is a dynamic table that refreshes within `target_lag` on the tenant's warehouse;
with all measurement fragments that is over 100 tables. Raise `target_lag` or narrow
`measurement_tables` (for example `c8y_SewPump%`) if warehouse credits matter more than freshness.

## 1. In Snowflake and BDC

BDC accepts only Snowflake-managed Iceberg V3 tables (copy-on-write, `COMPATIBLE` serialization)
with a primary key, one database per data product. The notebook creates them as dynamic Iceberg
tables that refresh at most `target_lag` (10 minutes) behind the source.

1. Run [`cumulocity_build_up.ipynb`](../cumulocity_build_up.ipynb) for the tenant.
2. Check the connector: `SHOW ZEROCOPY CONNECTORS IN ACCOUNT`. SAP creates
   `CONNECTORS.ZEROCOPY.DEFAULT_SAP_BDC_CONNECTOR` when the SAP Snowflake system joins the
   formation; its status must be `CONNECTED`.
3. In `cumulocity_bdc_data_product.ipynb`, set `catalog_name`, `share_name` and the ORD texts, then
   run sections 1 to 4. They create the database, the share and the tables, and change nothing in BDC.
   `bdc_csn_preview` shows the CSN document.
4. Run section 5. It enables share-back on the connector, adds the share and publishes. BDC extracts
   the metadata within a few minutes (*Catalog & Marketplace → Metadata Extractions →
   snowflake-…*); then the data product is in the catalog with lifecycle and release status Active.
5. Run section 6 (task graph) and section 7 (checks).

## 2. Republish on schema change

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

## 3. Consuming the data product

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
[../../databricks/sap-bdc/README.md](../../databricks/sap-bdc/README.md)):

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

## From an Iceberg change to Datasphere

Measured on 2026-11-07 with a new measurement fragment (`c8y_BdcFlowTest`, 120 tables):

| # | Step | How | Time |
|---|---|---|---|
| 1 | Lake → `CUMULOCITY_ICEBERG_<T>` | Catalog-linked database; Snowflake syncs the catalog itself | ~2 min |
| 2 | `OPS.REBUILD_ON_SCHEMA_CHANGE` → `OPS.BDC_CHECK` | Task every 15 minutes; compares a fingerprint of the source columns | 0–15 min |
| 3 | `OPS.BDC_CREATE_TABLES` | Creates or replaces only the dynamic Iceberg tables whose definition changed | ~1 min |
| 4 | `OPS.BDC_PUBLISH` | Sends the CSN with `SYSTEM$SAP_PUBLISH_DATA_PRODUCT` | ~1 min |
| 5 | BDC metadata extraction | Starts by itself after the publish | ~1 min |
| 6 | Datasphere: *Reinstall Data Product* | **Manual**, no API | 6–8 min when it works |
| | New rows only | Dynamic tables refresh within `target_lag` (10 minutes); Federation reads live | ≤ 10 min, no steps 2–6 |

Steps 1 to 5 took under 7 minutes. *Check for Schema Changes* doesn't add new tables, so a schema change
needs a reinstall.

## Where it gets stuck: Datasphere

The delays and failures are all in the last step, on SAP's side:

- **Manual.** Datasphere has no API or CLI for *Install*, *Reinstall* or *Check for Schema Changes*.
- **SAP's side lags behind BDC, sometimes by hours.** Tables we added or replaced: "Remote object ... could
  not be found" and stale data on 2026-11-06, fine the next morning. Changed column types: reinstalls 2 to 6
  minutes after the publish still imported the previous definition (2026-11-07, 2026-11-09). Nothing on our
  side shows or triggers this sync; wait and retry.
- **Installed tables keep their column types.** A reinstall can't change a column's type ("MISMATCH IN DATA
  TYPE PRECISION/SCALE"). Keep the types of shared tables stable.
- **All or nothing.** One failing table fails the whole reinstall (120 saved, 0 deployed). The tables
  installed before stay as they were.

What we do about it: `BDC_CREATE_TABLES` replaces only changed tables, and column types stay stable. Expect
schema changes to reach Datasphere after a manual reinstall, sometimes hours later. New rows need none of
this.
