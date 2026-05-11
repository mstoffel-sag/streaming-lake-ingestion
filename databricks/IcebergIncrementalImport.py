# Databricks notebook source
# DBTITLE 1,Install packages
# MAGIC %pip install --upgrade duckdb "pyiceberg[s3fs]" typing_extensions "pyarrow>=16.0.0"

# COMMAND ----------

# DBTITLE 1,Restart Python
dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Connect to Polaris Iceberg catalog
from pyiceberg.catalog import load_catalog
from pyiceberg import __version__
import pyarrow.types
print("Version of pyiceberg: " + __version__)

# Compatibility shim: PyIceberg 0.11.1 requires pa.types.is_string_view (PyArrow 16+)
if not hasattr(pyarrow.types, 'is_string_view'):
    pyarrow.types.is_string_view = lambda t: False

# 1. Fetch credentials
polaris_oauth_client_id = dbutils.secrets.get(scope="CumulocityPolarisIcebergS3", key="polaris_oauth_client_id")
polaris_oauth_client_secret = dbutils.secrets.get(scope="CumulocityPolarisIcebergS3", key="polaris_oauth_client_secret")
polaris_oauth_token_url = dbutils.secrets.get(scope="CumulocityPolarisIcebergS3", key="polaris_oauth_token_url")
polaris_oauth_scope = dbutils.secrets.get(scope="CumulocityPolarisIcebergS3", key="polaris_oauth_scope")
polaris_base_url = dbutils.secrets.get(scope="CumulocityPolarisIcebergS3", key="polaris_base_url")
polaris_warehouse = dbutils.secrets.get(scope="CumulocityPolarisIcebergS3", key="polaris_warehouse")

aws_access_key = dbutils.secrets.get(scope="CumulocityPolarisIcebergS3", key="aws_access_key")
aws_secret_key = dbutils.secrets.get(scope="CumulocityPolarisIcebergS3", key="aws_secret_key")
aws_region = dbutils.secrets.get(scope="CumulocityPolarisIcebergS3", key="aws_region")

# 2. Connect to Polaris Iceberg catalog
catalog = load_catalog(
    "polaris",
    **{
        "type": "rest",
        "uri": polaris_base_url,
        "oauth.token.url": polaris_oauth_token_url,
        "credential": f"{polaris_oauth_client_id}:{polaris_oauth_client_secret}",
        "scope": polaris_oauth_scope,
        "warehouse": polaris_warehouse,
        "s3.access-key-id": aws_access_key,
        "s3.secret-access-key": aws_secret_key,
        "s3.region": aws_region,
        "py-io-impl": "pyiceberg.io.fsspec.FsspecFileIO"
    }
)

catalog.list_namespaces()
catalog._session.headers.pop("X-Iceberg-Access-Delegation", None)

print("Polaris catalog connected successfully.")

# COMMAND ----------

# DBTITLE 1,Discover all tables in the catalog
# 3. Discover all namespaces and tables in the catalog
all_tables = []

namespaces = catalog.list_namespaces()
print(f"Found {len(namespaces)} namespace(s): {namespaces}")

for ns in namespaces:
    ns_name = ns[0] if isinstance(ns, tuple) else ns
    tables = catalog.list_tables(ns_name)
    for tbl in tables:
        all_tables.append(tbl)
        print(f"  Found table: {tbl[0]}.{tbl[1]}")

print(f"\nTotal tables to import: {len(all_tables)}")

# COMMAND ----------

# DBTITLE 1,Incremental import: append new data since last run
# 4. Incremental import: detect watermark per table and append only new data
import duckdb
import json
import time
import uuid
import numpy as np
import pandas as pd_lib
from decimal import Decimal
from datetime import datetime, timezone, date
from pyspark.sql.functions import monotonically_increasing_id, col, lit, current_timestamp
from pyspark.sql.types import StringType, LongType
from pyiceberg.types import TimestampType, TimestamptzType
from pyiceberg.expressions import And, GreaterThan, LessThanOrEqual

# Initialize DuckDB (fallback for equality deletes)
con = duckdb.connect()
con.execute("INSTALL iceberg")
con.execute("LOAD iceberg")
con.execute(f"SET s3_access_key_id='{aws_access_key}'")
con.execute(f"SET s3_secret_access_key='{aws_secret_key}'")
con.execute(f"SET s3_region='{aws_region}'")
print("DuckDB initialized (fallback for equality deletes).")

# Current time as upper bound for this run
run_end_time = datetime.now(timezone.utc)
print(f"Run end time (upper bound): {run_end_time.isoformat()}")


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal and datetime objects."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


def safe_json_dumps(x):
    """Safely serialize to JSON, handling pd.NA, NaN, and None."""
    if x is None:
        return None
    try:
        if pd_lib.isna(x):
            return None
    except (ValueError, TypeError):
        pass
    if isinstance(x, np.ndarray):
        return json.dumps(x.tolist(), cls=DecimalEncoder)
    return json.dumps(x, cls=DecimalEncoder)


def flatten_pandas_df(pdf):
    """
    Expand dict columns (from Arrow structs/maps) into flat columns.
    Structs with <=20 keys are expanded; others and lists become JSON strings.
    """
    cols_to_drop = []
    new_cols = {}

    for col_name in pdf.columns:
        if pdf[col_name].dtype == object:
            sample = pdf[col_name].dropna().head(10)
            if len(sample) == 0:
                continue

            first_val = sample.iloc[0]

            if isinstance(first_val, dict):
                keys_set = set()
                for val in sample:
                    if isinstance(val, dict):
                        keys_set.update(val.keys())

                if len(keys_set) <= 20:
                    cols_to_drop.append(col_name)
                    for key in sorted(keys_set):
                        flat_col_name = f"{col_name}_{key}"
                        new_cols[flat_col_name] = pdf[col_name].apply(
                            lambda x, k=key: x.get(k) if isinstance(x, dict) else None
                        )
                        if new_cols[flat_col_name].apply(
                            lambda x: isinstance(x, Decimal)
                        ).any():
                            new_cols[flat_col_name] = new_cols[flat_col_name].apply(
                                lambda x: float(x) if isinstance(x, Decimal) else x
                            )
                else:
                    pdf[col_name] = pdf[col_name].apply(safe_json_dumps)

            elif isinstance(first_val, (list, np.ndarray)):
                # Lists and numpy arrays: serialize to JSON strings
                pdf[col_name] = pdf[col_name].apply(safe_json_dumps)

    if cols_to_drop:
        pdf = pdf.drop(columns=cols_to_drop)
        for new_col_name, series in new_cols.items():
            pdf[new_col_name] = series

    # Second pass: catch any remaining array-like or datetime columns
    for col_name in pdf.columns:
        if pdf[col_name].dtype == object:
            sample = pdf[col_name].dropna().head(5)
            if len(sample) > 0:
                first_val = sample.iloc[0]
                if isinstance(first_val, (list, np.ndarray)):
                    pdf[col_name] = pdf[col_name].apply(safe_json_dumps)
                elif isinstance(first_val, (datetime, date)):
                    pdf[col_name] = pdf[col_name].apply(
                        lambda x: x.isoformat() if isinstance(x, (datetime, date)) else x
                    )

    return pdf


def get_target_schema(target_table_name):
    """
    Get the schema of the existing Delta table as a dict: {col_name: dataType}.
    Returns None if the table doesn't exist.
    """
    try:
        target_df = spark.table(target_table_name)
        return {field.name: field.dataType for field in target_df.schema.fields}
    except Exception:
        return None


def get_watermark(target_table_name, time_col_name):
    """
    Get the max timestamp (watermark) from the existing Delta table.
    Returns the watermark as ISO string, or None if the table doesn't exist or is empty.
    """
    try:
        result = spark.sql(f"SELECT MAX(`{time_col_name}`) as max_ts FROM {target_table_name}")
        max_ts = result.collect()[0]["max_ts"]
        if max_ts is not None:
            return max_ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        return None
    except Exception:
        # Table doesn't exist yet
        return None


def find_time_column(iceberg_schema):
    """Find the time column from the Iceberg schema."""
    for field in iceberg_schema.fields:
        if field.name in ["time", "lastUpdated", "creationTime"]:
            is_tz = isinstance(field.field_type, TimestamptzType)
            return field.name, is_tz
    return None, False


def build_incremental_filter(time_col_name, is_tz, watermark, end_time):
    """
    Build a PyIceberg filter for: time_col > watermark AND time_col <= end_time.
    Uses GreaterThan (exclusive) to avoid re-importing the last row.
    """
    end_str = end_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    if is_tz:
        watermark_ts = f"{watermark}+00:00"
        end_ts = f"{end_str}+00:00"
    else:
        watermark_ts = watermark
        end_ts = end_str

    return And(
        GreaterThan(time_col_name, watermark_ts),
        LessThanOrEqual(time_col_name, end_ts)
    )


def read_with_pyiceberg(iceberg_table, time_filter):
    """Try reading with PyIceberg (fast, uses partition pruning). Raises on equality deletes."""
    if time_filter:
        scan = iceberg_table.scan(row_filter=time_filter)
    else:
        scan = iceberg_table.scan()
    arrow_table = scan.to_arrow()
    return arrow_table.to_pandas()


def read_with_duckdb(metadata_location, time_col_name, is_tz, watermark, end_time):
    """Fallback: read with DuckDB (handles equality deletes)."""
    end_str = end_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    if time_col_name:
        if is_tz:
            wm_ts = f"{watermark}+00:00"
            end_ts = f"{end_str}+00:00"
        else:
            wm_ts = watermark
            end_ts = end_str
        query = f"""
            SELECT * FROM iceberg_scan('{metadata_location}')
            WHERE \"{time_col_name}\" > '{wm_ts}'::TIMESTAMP
              AND \"{time_col_name}\" <= '{end_ts}'::TIMESTAMP
        """
    else:
        query = f"SELECT * FROM iceberg_scan('{metadata_location}')"

    duck_result = con.execute(query)
    return duck_result.fetchdf()


results = []

for ns_name, table_name in all_tables:
    full_path = f"{ns_name}.{table_name}"
    target_table_name = full_path.replace(".", "_")

    print(f"\n{'='*60}")
    print(f"Processing: {full_path} -> {target_table_name}")
    print(f"{'='*60}")

    try:
        t0 = time.time()
        iceberg_table = catalog.load_table(full_path)
        metadata_location = iceberg_table.metadata_location

        # Find time column
        time_col_name, is_tz = find_time_column(iceberg_table.schema())

        # Get watermark from existing Delta table
        watermark = None
        if time_col_name:
            watermark = get_watermark(target_table_name, time_col_name)

        if watermark:
            print(f"  Watermark (last imported): {watermark}")
            print(f"  Fetching data from {watermark} to {run_end_time.isoformat()}")
            time_filter = build_incremental_filter(time_col_name, is_tz, watermark, run_end_time)
        elif time_col_name:
            print(f"  No existing data \u2014 full initial load")
            # Full load for first run (no watermark)
            time_filter = None
        else:
            print(f"  No time column \u2014 full load (table will be overwritten)")
            time_filter = None

        # Strategy: try PyIceberg first (fast), fall back to DuckDB for equality deletes
        reader_used = "pyiceberg"
        try:
            pdf = read_with_pyiceberg(iceberg_table, time_filter)
        except Exception as pyiceberg_err:
            if "equality deletes" in str(pyiceberg_err).lower():
                print(f"  \u26a0\ufe0f PyIceberg failed (equality deletes) \u2014 falling back to DuckDB...")
                reader_used = "duckdb"
                if watermark:
                    pdf = read_with_duckdb(metadata_location, time_col_name, is_tz, watermark, run_end_time)
                else:
                    pdf = read_with_duckdb(metadata_location, None, None, None, run_end_time)
            else:
                raise pyiceberg_err

        row_count = len(pdf)
        elapsed = time.time() - t0

        if row_count == 0:
            print(f"  SKIPPED: No new data since last import. ({elapsed:.1f}s, {reader_used})")
            results.append({"table": full_path, "status": "skipped", "reason": "no new data", "rows": 0})
            continue

        # Flatten struct/dict columns and serialize lists to JSON strings
        pdf = flatten_pandas_df(pdf)

        # Fix: cast all-null columns to string to avoid void type
        for c in pdf.columns:
            if pdf[c].isna().all():
                pdf[c] = pdf[c].astype("object")

        # Convert to Spark DataFrame
        df = spark.createDataFrame(pdf)

        # Fix: cast NullType columns to match existing target table schema
        # If the target table exists, use its types; otherwise default to StringType
        existing_schema = get_target_schema(target_table_name)
        for field in df.schema.fields:
            if str(field.dataType) == "NullType()":
                if existing_schema and field.name in existing_schema:
                    target_type = existing_schema[field.name]
                    df = df.withColumn(field.name, lit(None).cast(target_type))
                else:
                    df = df.withColumn(field.name, lit(None).cast(StringType()))

        # Generate unique row_id using offset from existing max
        # This ensures no collisions across incremental runs
        try:
            max_id_row = spark.sql(f"SELECT COALESCE(MAX(row_id), -1) as max_id FROM {target_table_name}").collect()
            id_offset = max_id_row[0]["max_id"] + 1
        except Exception:
            id_offset = 0

        df = df.withColumn("row_id", monotonically_increasing_id() + lit(id_offset).cast(LongType()))

        # Write mode depends on whether table has a time column (incremental) or not (full replace)
        if time_col_name:
            # Append new data
            df.write.mode("append").option("mergeSchema", "true").saveAsTable(target_table_name)
            write_mode = "append"
        else:
            # No time column \u2014 overwrite entire table each run
            df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(target_table_name)
            write_mode = "overwrite"

        elapsed = time.time() - t0
        print(f"  SUCCESS: {row_count} rows {write_mode}ed to '{target_table_name}' ({elapsed:.1f}s, {reader_used})")
        print(f"  Schema: {[f.name for f in df.schema.fields]}")
        results.append({"table": full_path, "status": "success", "rows": row_count, "target": target_table_name, "reader": reader_used, "mode": write_mode, "seconds": round(elapsed, 1)})

    except Exception as e:
        error_msg = str(e)[:300]
        print(f"  ERROR: {error_msg}")
        results.append({"table": full_path, "status": "error", "reason": error_msg, "rows": 0})

con.close()
print(f"\nDone. Processed {len(results)} tables.")

# COMMAND ----------

# DBTITLE 1,Import summary
# 5. Summary of all imports
import pandas as pd

df_summary = pd.DataFrame(results)
print(f"\n{'='*60}")
print("IMPORT SUMMARY")
print(f"{'='*60}")
print(f"Total tables processed: {len(results)}")
print(f"Successful: {len(df_summary[df_summary['status'] == 'success'])}")
print(f"Skipped (no new data): {len(df_summary[df_summary['status'] == 'skipped'])}")
print(f"Errors: {len(df_summary[df_summary['status'] == 'error'])}")
print(f"\nTotal new rows imported: {df_summary[df_summary['status'] == 'success']['rows'].sum()}")
print()
display(df_summary)

# COMMAND ----------

# DBTITLE 1,Ensure primary key constraints exist
# 6. Ensure primary key constraints exist on all imported tables
# Only adds constraints if they don't already exist (idempotent)

pk_results = []

for row in results:
    if row["status"] != "success":
        continue
    
    table_name = row["target"]
    constraint_name = f"pk_{table_name}"
    
    try:
        # Set row_id as NOT NULL (required for PK)
        spark.sql(f"ALTER TABLE {table_name} ALTER COLUMN row_id SET NOT NULL")
        
        # Add the primary key constraint on row_id
        spark.sql(f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} PRIMARY KEY (row_id)")
        
        print(f"  \u2713 {table_name}: PRIMARY KEY (row_id) added")
        pk_results.append({"table": table_name, "status": "success"})
    except Exception as e:
        error_msg = str(e)[:300]
        if "already_exist" in error_msg.lower() or "already exists" in error_msg.lower():
            print(f"  \u2713 {table_name}: PRIMARY KEY already exists")
            pk_results.append({"table": table_name, "status": "exists"})
        else:
            print(f"  \u2717 {table_name}: {error_msg}")
            pk_results.append({"table": table_name, "status": "error"})

print(f"\nPrimary keys ensured: {len([r for r in pk_results if r['status'] in ('success', 'exists')])} / {len(pk_results)}")
