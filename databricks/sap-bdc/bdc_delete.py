# Databricks notebook source
# MAGIC %md
# MAGIC ## Remove the data product from SAP Business Data Cloud and drop the Delta Share
# MAGIC
# MAGIC The reverse of `bdc_connect`. Uninstall the data product in every consuming system first (in Datasphere:
# MAGIC *Catalog & Marketplace → Data Product Access → Agreements →* the agreement *→ End Agreement*), then run all
# MAGIC cells:
# MAGIC 1. Deletes the share and its data product in BDC (`drop_cascade`: the tables and schemas BDC registered
# MAGIC    for it). It runs first because the SDK requests its token for an existing share.
# MAGIC 2. Drops the Delta Share and its rows in the publish state (`_bdc_publish_state`) in Databricks.
# MAGIC
# MAGIC The source tables are not touched. Remove the `bdc_*` tasks from the import job first, or the next schema
# MAGIC change publishes everything again.

# COMMAND ----------

# MAGIC %pip install sap-bdc-connect-sdk==1.1.18

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

dbutils.widgets.text("catalog", "factory", "Source catalog")
dbutils.widgets.text("schema", "adhoc-demo_eu-latest-t2180777119", "Source schema")
dbutils.widgets.text("share_name", "cumulocity_t2180777119", "Share / data product name")
dbutils.widgets.text("recipient", "sap-business-data-cloud", "BDC recipient")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
share_name = dbutils.widgets.get("share_name")
recipient = dbutils.widgets.get("recipient")

# COMMAND ----------

# DBTITLE 1,Delete the share and data product in BDC
from bdc_connect_sdk.auth import BdcConnectClient, DatabricksClient

print(BdcConnectClient(DatabricksClient(dbutils, recipient)).delete_share(share_name, drop_cascade=True))
print(f"Share '{share_name}' deleted in BDC.")

# COMMAND ----------

# DBTITLE 1,Drop the Delta Share and its publish state
spark.sql(f"DROP SHARE IF EXISTS `{share_name}`")
# Only this share's rows: other shares of the same schema keep their state
state = f"`{catalog}`.`{schema}`._bdc_publish_state"
if spark.catalog.tableExists(state):
    spark.sql(f"DELETE FROM {state} WHERE share_name = '{share_name}'")
print(f"Delta Share '{share_name}' and its publish state dropped.")
