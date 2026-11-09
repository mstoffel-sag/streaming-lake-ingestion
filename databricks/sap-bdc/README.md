# SAP BDC data product (Databricks)

Publishes the tables of the Databricks import ([../README.md](../README.md)) as a data product to SAP
Business Data Cloud (BDC) and installs it in SAP Datasphere. The Snowflake variant is in
[../../snowflake/sap-bdc/README.md](../../snowflake/sap-bdc/README.md).

![Data flow of the Databricks and Snowflake data products into SAP Datasphere](img/sap-bdc-data-flow.png)

Editable source: [img/sap-bdc-data-flow.drawio](img/sap-bdc-data-flow.drawio).

| File | Purpose |
|---|---|
| `bdc_connect.py` | Creates the Delta Share from the import tables and publishes it to BDC with ORD and CSN |
| `bdc_tables.py` | Table selection and schema fingerprint (workspace file, used by `bdc_connect` and `CheckBdcSchema`) |
| `CheckBdcSchema.py` | Task `bdc_check`: decides whether a republish is needed |
| `RefreshMeasurementFact.py` | Task `measurement_fact`: rebuilds `curated_measurement` |
| `bdc_delete.py` | Removes the data product from BDC and drops the Delta Share |

## Contents

Delta Share `cumulocity_t2180777119`, recipient `sap-business-data-cloud`:

| In the share | Content |
|---|---|
| `cdc_<namespace>.cdc_<namespace>_<table>` | Change log per Iceberg table: alarms, events, inventory, one table per measurement fragment |
| `latest_<namespace>.latest_<namespace>_<table>` | Current state per object (inventory) |
| `curated.curated_measurement` | All measurement series in long format: `id, fragment, series, time, source, value, unit`, key `(id, fragment, series)` |

- New Iceberg tables join automatically; helper tables (`_*`, `grafana_*`, `internal_*`) stay out.
- Tables keep their full Databricks name. Datasphere names remote tables `<share>:v1.<table>` without the
  schema, so short names collided (`cdc_inventory.c8y_agent`, `latest_inventory.c8y_agent`).
- The CSN declares timestamps as `cds.Timestamp`: Datasphere rejects the SDK's `cds.DateTime`.
- The import writes no `struct` columns, which the CSN can't express.

## Setup

**Once, by the admins**
- Databricks metastore: `CREATE SHARE` for you, `USE RECIPIENT` on `sap-business-data-cloud` (only the BDC
  operators can grant it).
- Secret scope `sap-bdc-connect-sdk` with `api_url`, `tenant` and `token_audience`.
- Datasphere: space `CUMULOCITY` with you as a member who may install data products; Datasphere enabled as a
  target for data products from the SAP Databricks system.
- BDC: the approver role for the domain.

**Publish**
1. Import `bdc_connect`, `CheckBdcSchema`, `RefreshMeasurementFact` and `bdc_delete` as notebooks into the
   folder of the import notebook, and `bdc_tables.py` as a file.
2. Import job: add task `measurement_fact` (depends on `import`, *Run if* **All done**) and run the job once.
3. Fix the table names now: renaming or removing tables after the first install breaks Datasphere.
4. Run `bdc_connect`. It ends with `Share registered.`, `CSN uploaded.` and `Data product '...' published`.
5. Import job: add the republish tasks below.

## Republish on schema change

| Task | Does |
|---|---|
| `bdc_check` | After `import` and `measurement_fact`: SHA-256 fingerprint over the shared tables, names, columns, types and nullability, compared with `_bdc_publish_state`. Sets `changed`. Takes seconds. |
| `bdc_changed` | Condition `{{tasks.bdc_check.values.changed}} == "true"` |
| `bdc_publish` | Runs `bdc_connect` and stores the new fingerprint |

A new column, changed type or new Iceberg table is republished within one import cycle. To force a
republish, delete the share's rows from `_bdc_publish_state` or run `bdc_connect`. Tables that drop out of
the selection are removed from the share, which breaks their consumers in Datasphere.

## Install in Datasphere

The same steps apply to the Snowflake product.

1. BDC cockpit, *Catalog & Marketplace → Metadata Extractions*: wait until the source system
   (`databricks-6918e1f0`) shows *Synchronized* with a time **after** the publish.
2. **Datasphere** (the BDC cockpit cart doesn't offer it), *Catalog & Marketplace → Search → Data Products*:
   *Add to Cart*, open the cart, *Proceed*.
3. *Request Access*: space `CUMULOCITY`, a comment, no end date, accept the terms, *Send*.
4. BDC cockpit, *Governance → Access Management*: *Approve* the request.
5. Datasphere, *Catalog & Marketplace → Data Product Access → Agreements*: open the agreement, *Install Data
   Product*, delivery method **Federation** (reads live; the default Replication copies), *Install*.
6. Notifications (bell): wait for *Data Product Installation: Completed* with *Saved objects* equal to
   *Deployed objects*. On *Failed*, *Show More* names the table and column.
7. *Data Builder →* space `CUMULOCITY`: every table is a *Remote Table*, status *Deployed*, in the
   SAP-managed space `DATABRICKS6918E1F0`.

After a schema change: *Agreements →* the agreement *→ Check for Schema Changes* or *⋯ → Reinstall Data
Product*. *Check for Schema Changes* doesn't add new tables.

## Analytic Model for SAP Analytics Cloud

SAP Analytics Cloud reads Analytic Models, not remote tables. Space `CUMULOCITY` has one on
`curated_measurement`:

| Object | Type | Content |
|---|---|---|
| `DBX_DEVICE` | SQL view, Dimension | `latest_inventory_inventory`: `ID` (key, text `NAME`), type, site and asset attributes |
| `DBX_MEASUREMENT` | SQL view, Fact | `curated_measurement` plus `FRAGMENT_SERIES` and `DAY`; association `SOURCE` → `DBX_DEVICE.ID` |
| `DBX_MEASUREMENT_AM` | Analytic Model | Fact `DBX_MEASUREMENT`, dimension Device, calculated Average Value |

Build them in *Data Builder →* space `CUMULOCITY`. Each step ends with *Deploy*; if the status still says
*Not Deployed*, click *Deploy* again.

**1. Source tables.** Search for `curated`: the remote tables come from space `DATABRICKS6918E1F0`.

![Remote table curated_measurement in the Data Builder](img/01-remote-table.jpg)

**2. `DBX_DEVICE`.** *New SQL View*. Dragging a table from the *Repository* panel into the editor inserts its
full name.

![Dragging latest_inventory_inventory into the SQL editor](img/02-drag-source.jpg)

*Business Name* `Device (Databricks)`, *Semantic Usage* **Dimension**, then *Validate SQL*:

```sql
SELECT "id" AS "ID", "name" AS "NAME", "type" AS "TYPE", "site_code" AS "SITE_CODE",
       "site_type" AS "SITE_TYPE", "operating_region" AS "OPERATING_REGION", "catchment" AS "CATCHMENT",
       "process_stage" AS "PROCESS_STAGE", "asset_criticality" AS "ASSET_CRITICALITY",
       "operational_status" AS "OPERATIONAL_STATUS"
FROM "DATABRICKS6918E1F0.cumulocity_t2180777119:v1.latest_inventory_inventory"
WHERE "id" IS NOT NULL
```

![DBX_DEVICE: SQL and properties](img/03-device-view.jpg)

*Attributes → Edit*: `ID` as key, business names *Device ID* and *Device Name*, `NAME` semantic type
**Text**, `ID`'s *Text / Association* *Device Name*, so SAC shows names instead of IDs.

![DBX_DEVICE attributes: key, Text and text association](img/04-device-attributes.jpg)

**3. `DBX_MEASUREMENT`.** *New SQL View*, *Business Name* `Measurement (Databricks)`, *Semantic Usage*
**Fact**:

```sql
SELECT "id" AS "ID", "fragment" AS "FRAGMENT", "series" AS "SERIES",
       "fragment" || '.' || "series" AS "FRAGMENT_SERIES", "time" AS "TIME", TO_DATE("time") AS "DAY",
       "source" AS "SOURCE", "unit" AS "UNIT", "value" AS "VALUE", "value" AS "VALUE_MIN",
       "value" AS "VALUE_MAX", 1 AS "SAMPLES"
FROM "DATABRICKS6918E1F0.cumulocity_t2180777119:v1.curated_measurement"
```

`VALUE` appears three times because a measure has one aggregation; `SAMPLES` gives the average.
`FRAGMENT_SERIES` filters one series, since series names repeat across fragments.

![DBX_MEASUREMENT: SQL and properties](img/05-measurement-view.jpg)

*Attributes → Edit*: `UNIT` semantic type **Unit of Measure**.

![DBX_MEASUREMENT attributes](img/06-measurement-attributes.jpg)

`VALUE`, `VALUE_MIN`, `VALUE_MAX`, `SAMPLES`: *⋯ → Change to Measure*. *Measures → Edit*: aggregation SUM,
MIN, MAX, SUM; the value measures *Quantity with Unit*, *Unit Column* `Unit`.

![DBX_MEASUREMENT measures: aggregation and unit](img/07-measurement-measures.jpg)

*Associations → + → Association*, target `DBX_DEVICE`. Datasphere maps `ID` → `Device ID`, which is wrong:
delete that line and drag `SOURCE` onto *Device ID*.

![Association SOURCE to DBX_DEVICE.ID](img/08-association.jpg)

**4. `DBX_MEASUREMENT_AM`.** In `DBX_MEASUREMENT`, *Create Analytic Model*: it takes all measures and adds
*Device* through the association.

![Analytic Model with fact source and Device dimension](img/09-analytic-model.jpg)

*Measures → + → Calculated Measure*: *Average Value*, `VALUE / SAMPLES`.

![Calculated measure Average Value](img/10-average-measure.jpg)

**5. Check.** *Preview* with *Fragment and Series* in *Rows*; without a series the value measures show `•`
(mixed units). The preview read 14.65 million rows live through the share in about 15 seconds.

![Preview grouped by Fragment and Series](img/11-preview.jpg)

## What runs automatically

| Change | Databricks | BDC catalog | Datasphere |
|---|---|---|---|
| New rows | `import` every 8 min | — | Nothing: Federation reads live |
| New table, column or type | `import`, `bdc_check`, `bdc_publish` (~1 min) | Metadata extraction (~5 min) | **Manual** reinstall, 30+ min for 137 tables |
| Renamed or removed table | Same; renames come from `bdc_tables.py` | Same | **Manual** reinstall; old remote tables stay (only SAP support removes them) |

## Known issues on the SAP side

- **Manual.** Datasphere has no API or CLI to install or reinstall a data product.
- **Datasphere lags behind BDC, sometimes by hours.** A reinstall right after a publish can deploy the
  previous definition, or fail with "Remote object ... could not be found". Wait and retry.
- **Column types are frozen.** A reinstall can't change the type of an installed column ("MISMATCH IN DATA
  TYPE PRECISION/SCALE"). Keep types stable.
- **All or nothing.** One failing table fails the whole reinstall; the installed tables stay as they were.
- **No progress shown.** A reinstall shows only *Started* until it finishes. Wait for *Completed*.
- **Fixed version.** BDC Connect sets the ORD ID and version 1.0.0 itself. A new `share_name` gives a
  separate data product.

## Removing the data product

1. Remove the `bdc_*` tasks from the import job.
2. Datasphere, *Agreements →* the agreement *→ End Agreement*.
3. Run `bdc_delete`: deletes the data product in BDC, drops the Delta Share and its rows in
   `_bdc_publish_state`. The catalog entry disappears with the next metadata extraction.
