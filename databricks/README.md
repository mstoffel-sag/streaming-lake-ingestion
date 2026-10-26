# Databricks

Incrementally import Cumulocity Iceberg tables from the Polaris catalog into Delta tables.
The catalog vends S3 credentials, so no AWS keys are stored.

| File | Purpose |
|---|---|
| `Edit_Secrets.py` | Creates and edits the `CumulocityPolarisIcebergS3` secret scope (Polaris OAuth client, token URL, scope, base URL, warehouse; `aws_region` optional) |
| `IcebergIncrementalImport PyIceberg.ipynb` | Import via PyIceberg scans (**recommended**) |
| `IcebergIncrementalImport DuckDB.ipynb` | Import via DuckDB `read_parquet` on new data files |
| `bdc_connect.py` | Publishes a Delta Share as a data product to SAP Business Data Cloud |

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

Clear notebook outputs before committing.
