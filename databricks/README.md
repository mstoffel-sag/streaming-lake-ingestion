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

## How the import works

Per table:
1. **Snapshot check:** if the Iceberg snapshot ID matches the last import (`_iceberg_snapshot_tracking`), skip the table.
2. **Read new rows** between the last imported timestamp (`time`, `lastUpdated` or `creationTime`) and now; tables without a time column are overwritten.
3. **Flatten** nested columns (lists/complex types become JSON), add a unique `row_id`.
4. **Write** to Delta (append with `mergeSchema`, or overwrite), store snapshot ID and sequence number.
5. Ensure `PRIMARY KEY (row_id)` on every target table.

## PyIceberg vs. DuckDB

- **PyIceberg** applies Iceberg delete files, so updated or deleted source rows are handled
  correctly. Only if a table has equality deletes PyIceberg can't merge does it fall back to
  reading new files directly.
- **DuckDB** always reads new data files directly and ignores delete files. Faster for large
  append-only tables, but can re-import deleted or superseded rows. Use it only for append-only data.

Clear notebook outputs before committing.
