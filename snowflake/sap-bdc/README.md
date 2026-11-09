# SAP BDC data product (Snowflake)

`cumulocity_bdc_data_product.ipynb` publishes the Cumulocity tables of a tenant as a data product to SAP
Business Data Cloud. Setup, table layout, tasks and the Datasphere install are described in
[../README.md, section "SAP BDC data product"](../README.md#sap-bdc-data-product).

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
