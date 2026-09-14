Two notebooks incrementally import data from a Polaris Iceberg catalog (on S3) into Delta tables in Databricks. Both share the same connection, discovery, flatten/write, and snapshot-tracking logic — they differ only in the engine used to read Iceberg data.

## `IcebergIncrementalImport DuckDB.ipynb`

Reads via DuckDB's `iceberg` extension (`iceberg_scan`, `iceberg_metadata`).

Three-layer incremental detection:
- **Snapshot short-circuit** — compares the current Iceberg `snapshot_id` against the last-imported one in `_iceberg_snapshot_tracking`. If unchanged, the table is skipped with zero S3 access.
- **Manifest-level diff** — when the snapshot changed, queries `iceberg_metadata()` to find only the Parquet data files added since the stored `sequence_number`, then reads those files directly with `read_parquet`.
- **Time-based watermark** — within the selected files, filters rows using a time column (`time`, `lastUpdated`, or `creationTime`) between the last-imported max timestamp and the current run time. Tables without a time column get a full overwrite.

**Known issue:** the manifest-diff step reads new data files directly via `read_parquet`, bypassing Iceberg's delete files (positional/equality deletes). If the source table ever has row-level updates or deletes, this path can re-import rows that were actually deleted or superseded upstream. It's only safe for append-only tables.

**Notebook hygiene issue:** the file currently contains two full pipelines back to back — a refined version (snapshot short-circuit + manifest diff) followed by an older, simpler version (plain watermark filtering, no snapshot tracking at all). Running the notebook top-to-bottom executes the import twice with two different strategies. The older second copy should be deleted.

## `IcebergIncrementalImport PyIceberg.ipynb`

Reads via PyIceberg's own `table.scan(row_filter=...).to_arrow()` — no DuckDB dependency.

Same snapshot short-circuit as above, but instead of a hand-rolled manifest diff, it applies the time-based row filter directly to a scan of the table's current snapshot. PyIceberg's scan planner does its own file pruning (via partition/column stats) and, unlike the DuckDB manifest-diff path, correctly applies delete files by default — so updates/deletes on the source table are reflected correctly for the common case.

It also has an explicit, scoped fallback: if `scan().to_arrow()` raises because the table has equality deletes PyIceberg doesn't yet merge, it catches that specific error and falls back to reading the new data files directly via PyArrow (`_read_new_files`, using `inspect.entries()` to find files added since the last stored sequence number), applying the time filter in pandas afterwards. This fallback has the same correctness gap as the DuckDB manifest-diff (it bypasses delete merging) — but unlike the DuckDB notebook, it's only used when the primary, correct path actually fails, not as the unconditional default.

**Known bug still open:** the primary-key step calls `ALTER TABLE ... ADD CONSTRAINT ... PRIMARY KEY (row_id)` without first running `ALTER TABLE ... ALTER COLUMN row_id SET NOT NULL` (which the DuckDB version does). Unity Catalog requires PK columns to be `NOT NULL`, so this step is likely to fail as written — the notebook's last saved run shows "Primary keys ensured: 0 / 0", though that particular output is stale (from `results` being empty at the time that cell last ran) rather than confirmation either way.

**Format note:** this file was converted from a plain `.py` Databricks source script into a `.ipynb` with baked-in execution outputs (40-table listing, per-run timings, etc.), growing from ~14 KB to ~74 KB. That makes it noisier to diff/review in PRs than a plain script — worth clearing outputs before committing, or keeping the canonical source as `.py` and treating any `.ipynb` as a disposable run artifact.

## Which one is better

**`IcebergIncrementalImport PyIceberg.ipynb` is the better foundation**, once the PK bug above is fixed:
- **Correctness** — it respects Iceberg delete files by default; the DuckDB notebook's manifest-diff shortcut never does, even when the primary scan would otherwise succeed.
- **Fewer moving parts** — no DuckDB + DuckDB Iceberg extension (a newer/less mature code path) alongside PyIceberg; file pruning and snapshot planning are handled by the library that owns the Iceberg spec instead of being hand-rolled with `iceberg_metadata()`.

The DuckDB notebook's manifest-diff *can* be faster for very large append-only tables since it avoids the full scan-planning overhead, so it's not without merit — but that gain isn't worth the silent-correctness risk for any table where rows can be updated or deleted.

**Before switching over:** fix the `SET NOT NULL` step in the PyIceberg PK cell, clear or avoid committing bulky notebook outputs, and delete the duplicate second pipeline from the DuckDB notebook (or the notebook entirely, if PyIceberg becomes the sole implementation).

## Shared pipeline (both notebooks)

Data pipeline per table:
1. Read new/changed rows into a pandas DataFrame via the notebook's engine.
2. `flatten_pandas_df` expands nested dict columns into flat columns and serializes lists/complex types to JSON.
3. `spark.createDataFrame` converts to a Spark DataFrame; `NullType` columns are resolved against the existing target schema, and a unique `row_id` is generated.
4. Data is written via `saveAsTable` (append with `mergeSchema` for time-based tables, overwrite with `overwriteSchema` otherwise).
5. The new snapshot ID and sequence number are persisted via `MERGE` into `_iceberg_snapshot_tracking`.

Post-processing: prints an import summary and ensures `PRIMARY KEY (row_id)` constraints exist on all target tables.
