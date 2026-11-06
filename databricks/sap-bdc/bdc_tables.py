"""Table selection and schema fingerprint of the BDC data product.

Imported by bdc_connect and CheckBdcSchema (a plain workspace file next to them, not a notebook),
so both work on the same table set.
"""
import hashlib
import re

# <namespace>_<table> as written by the import, e.g. cdc_measurement_c8y_sewpump_health; the namespace
# (cdc_alarm, cdc_event, cdc_inventory, cdc_measurement, latest_inventory, ...) becomes the schema in the share.
IMPORT_TABLE = re.compile(r"^((?:cdc|latest)_[a-z0-9]+)_(.+)$")
FACT_TABLE = "curated_measurement"  # long-format measurements, written by RefreshMeasurementFact
STATE_TABLE = "_bdc_publish_state"  # last published fingerprint per share


def share_tables(spark, catalog, schema):
    """Source table -> name inside the share (<schema>.<table>).

    Every table the import writes: the cdc_* change logs and the latest_* current state, under their
    Iceberg namespace, plus the measurement fact table under curated. New Iceberg tables join automatically;
    helper tables (_*, grafana_*, internal_*) don't match.

    The table part keeps the full import name (cdc_inventory.cdc_inventory_c8y_agent, not
    cdc_inventory.c8y_agent): Datasphere names remote tables <share>.<table> without the schema, so
    cdc_inventory.c8y_agent and latest_inventory.c8y_agent would collide and the install drops one of them.
    """
    tables = {}
    for row in spark.sql(f"SHOW TABLES IN `{catalog}`.`{schema}`").collect():
        match = IMPORT_TABLE.match(row["tableName"])
        if match and not row["isTemporary"]:
            tables[row["tableName"]] = f"{match.group(1)}.{row['tableName']}"
    if spark.catalog.tableExists(f"`{catalog}`.`{schema}`.{FACT_TABLE}"):
        tables[FACT_TABLE] = f"curated.{FACT_TABLE}"
    return tables


def schema_fingerprint(spark, catalog, schema, tables):
    """SHA-256 over the shared tables, their aliases, columns and types: anything that changes the
    share contents or the generated CSN changes the fingerprint."""
    names = ", ".join(f"'{t.lower()}'" for t in tables)
    rows = spark.sql(f"""
        SELECT table_name, column_name, full_data_type, is_nullable
        FROM `{catalog}`.information_schema.columns
        WHERE table_schema = '{schema}' AND table_name IN ({names})""").collect()
    aliases = {t.lower(): a for t, a in tables.items()}
    lines = sorted(f"{aliases[r['table_name']]}|{r['column_name']}|{r['full_data_type']}|{r['is_nullable']}"
                   for r in rows)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _state(catalog, schema):
    return f"`{catalog}`.`{schema}`.{STATE_TABLE}"


def last_published(spark, catalog, schema, share_name):
    """Fingerprint of the last successful publish, or None."""
    if not spark.catalog.tableExists(_state(catalog, schema)):  # backticks: the schema name has hyphens
        return None
    row = spark.sql(f"SELECT fingerprint FROM {_state(catalog, schema)} WHERE share_name = '{share_name}' "
                    f"ORDER BY published_at DESC LIMIT 1").first()
    return row["fingerprint"] if row else None


def store_published(spark, catalog, schema, share_name, fingerprint):
    spark.sql(f"CREATE TABLE IF NOT EXISTS {_state(catalog, schema)} "
              f"(share_name STRING, fingerprint STRING, published_at TIMESTAMP) USING DELTA")
    spark.sql(f"INSERT INTO {_state(catalog, schema)} VALUES ('{share_name}', '{fingerprint}', current_timestamp())")
