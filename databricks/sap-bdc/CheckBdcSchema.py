# Databricks notebook source
# MAGIC %md
# MAGIC ## Check whether the BDC data product needs a republish
# MAGIC
# MAGIC Compares the schema fingerprint of the shared tables (table set, columns, types; see `bdc_tables.py`)
# MAGIC with the last successful publish. Sets the task value `changed` (`"true"` / `"false"`); the import job
# MAGIC runs `bdc_connect` only when it is `"true"`. Runs in seconds and installs nothing.

# COMMAND ----------

from bdc_tables import last_published, schema_fingerprint, share_tables

dbutils.widgets.text("catalog", "factory", "Source catalog")
dbutils.widgets.text("schema", "adhoc-demo_eu-latest-t2180777119", "Source schema")
dbutils.widgets.text("share_name", "cumulocity_adhoc_demo", "Share / data product name")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
share_name = dbutils.widgets.get("share_name")

current = schema_fingerprint(spark, catalog, schema, share_tables(spark, catalog, schema))
previous = last_published(spark, catalog, schema, share_name)
changed = current != previous

dbutils.jobs.taskValues.set(key="changed", value=str(changed).lower())
print(f"'{share_name}': fingerprint {current[:12]}, last published {(previous or 'never')[:12]} -> "
      + ("republish" if changed else "unchanged"))
