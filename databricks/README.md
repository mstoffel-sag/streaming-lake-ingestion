This notebook incrementally imports data from a Polaris Iceberg catalog (on S3) into Delta tables in Databricks, using DuckDB as the read engine.

Connection layer (cells 3–4): Authenticates to Polaris via OAuth credentials stored in Databricks secrets, connects to the REST catalog, and discovers all namespaces and tables automatically.

Three-layer incremental detection (cell 5):

Snapshot short-circuit — compares the current Iceberg snapshot_id against the last-imported one in _iceberg_snapshot_tracking. If unchanged, the table is skipped with zero S3 access.
Manifest-level diff — when the snapshot changed, queries iceberg_metadata() in DuckDB to identify only the Parquet files added since the stored sequence_number. This avoids scanning the full table.
Time-based watermark — within new files, filters rows using a time column (time, lastUpdated, or creationTime) between the last-imported MAX timestamp and the current run time. Tables without a time column get a full overwrite.
Data pipeline per table:

DuckDB reads Iceberg/Parquet data into a pandas DataFrame
flatten_pandas_df expands nested dict columns into flat columns and serializes lists/complex types to JSON
Spark createDataFrame converts to a Spark DataFrame, NullType columns are resolved against the existing target schema, and a unique row_id is generated
Data is written via saveAsTable (append with mergeSchema for time-based tables, overwrite with overwriteSchema otherwise)
The new snapshot ID and sequence number are persisted via MERGE into the tracking table
Post-processing (cells 6–7): Prints an import summary and ensures PRIMARY KEY (row_id) constraints exist on all target tables.

