# Databricks notebook source
# MAGIC %md
# MAGIC ## Refresh the Grafana device/series lookup
# MAGIC
# MAGIC Materializes `grafana_device_series_v` (created by `grafana/series_views.py`) into the Delta table
# MAGIC `grafana_device_series`, which the Grafana dashboard reads for its device and series lists.
# MAGIC Runs as a task after the import in the import job.

# COMMAND ----------

dbutils.widgets.text("catalog", "factory", "Catalog")
dbutils.widgets.text("schema", "adhoc-demo_eu-latest-t2180777119", "Schema")
target = f"`{dbutils.widgets.get('catalog')}`.`{dbutils.widgets.get('schema')}`"

spark.sql(f"CREATE OR REPLACE TABLE {target}.grafana_device_series AS SELECT * FROM {target}.grafana_device_series_v")
print(spark.sql(f"SELECT COUNT(*) AS pairs, COUNT(DISTINCT device_id) AS devices FROM {target}.grafana_device_series").first())
