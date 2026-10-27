# Databricks notebook source
# MAGIC %md
# MAGIC ## Publish a Delta Share as a data product to SAP Business Data Cloud
# MAGIC
# MAGIC Creates (or updates) a Delta Share with the selected import tables, grants it to the BDC recipient,
# MAGIC and publishes it as a data product with ORD metadata and a generated CSN schema, so it can be
# MAGIC consumed in SAP Datasphere.
# MAGIC
# MAGIC **Needs:** `CREATE SHARE` and `USE RECIPIENT` on the metastore (or share/recipient ownership), and
# MAGIC `SELECT` on the source tables. CSN generation supports boolean, string, int, bigint, double, decimal,
# MAGIC date and timestamp columns; every table should have a primary key (the import adds one on `row_id`).
# MAGIC
# MAGIC Run all cells. Re-running updates the share contents, metadata and schema.

# COMMAND ----------

# DBTITLE 1,Install SDK
# MAGIC %pip install sap-bdc-connect-sdk==1.1.18

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Data product configuration
dbutils.widgets.text("catalog", "factory", "Source catalog")
dbutils.widgets.text("schema", "adhoc-demo_eu-latest-t2180777119", "Source schema")
dbutils.widgets.text("share_name", "cumulocity_adhoc_demo", "Share / data product name")
dbutils.widgets.text("recipient", "sap-business-data-cloud", "BDC recipient")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
share_name = dbutils.widgets.get("share_name")
recipient = dbutils.widgets.get("recipient")

# Shared tables: source table name -> name inside the share (<share schema>.<table>).
# Alarms, the device/asset master and the sewage pump measurements.
SHARE_SCHEMA = "cumulocity"
tables = {"cdc_alarm_alarm": "alarm", "latest_inventory_inventory": "inventory"}
for row in spark.sql(f"SHOW TABLES IN `{catalog}`.`{schema}` LIKE 'cdc_measurement_c8y_sewpump_*'").collect():
    tables[row["tableName"]] = row["tableName"].replace("cdc_measurement_c8y_", "")

title = "Cumulocity adhoc-demo (eu-latest t2180777119)"
short_description = "Cumulocity alarms, inventory and sewage pump measurements"
description = (
    "Alarms (change log), the current device/asset inventory and the sewage pump measurement series "
    "from Cumulocity Streaming Lake Ingestion, imported from the Iceberg catalog every few minutes."
)
version = "1.0.0"

print(f"Share '{share_name}' with {len(tables)} table(s) from {catalog}.{schema}:")
for source, alias in sorted(tables.items()):
    print(f"  {source} -> {SHARE_SCHEMA}.{alias}")

# COMMAND ----------

# DBTITLE 1,Create the Delta Share and grant it to the BDC recipient
spark.sql(f"CREATE SHARE IF NOT EXISTS `{share_name}` COMMENT '{short_description}'")

shared = {r["name"]: r["shared_object"] for r in spark.sql(f"SHOW ALL IN SHARE `{share_name}`").collect() if r["type"] == "TABLE"}
for source, alias in sorted(tables.items()):
    name = f"{SHARE_SCHEMA}.{alias}"
    if name in shared:
        continue
    spark.sql(f"ALTER SHARE `{share_name}` ADD TABLE `{catalog}`.`{schema}`.`{source}` AS {name}")
    print(f"  added {name}")
for name in sorted(set(shared) - {f"{SHARE_SCHEMA}.{a}" for a in tables.values()}):
    spark.sql(f"ALTER SHARE `{share_name}` REMOVE TABLE {name}")
    print(f"  removed {name}")

spark.sql(f"GRANT SELECT ON SHARE `{share_name}` TO RECIPIENT `{recipient}`")
print(f"Share '{share_name}' granted to recipient '{recipient}'.")

# COMMAND ----------

# DBTITLE 1,Register the share in BDC with ORD metadata
from bdc_connect_sdk.auth import BdcConnectClient, DatabricksClient
from bdc_connect_sdk.utils import csn_generator

bdc_connect_client = BdcConnectClient(DatabricksClient(dbutils, recipient))

open_resource_discovery_information = {
    "@openResourceDiscoveryV1": {
        "title": title,
        "shortDescription": short_description,
        "description": description,
        "version": version,
        "releaseStatus": "active",
        "visibility": "public",
        "dataProducts": [
            {
                "ordId": f"sap.databricks:dataProduct:{share_name}:v1",
                "title": title,
                "shortDescription": short_description,
                "description": description,
                "version": version,  # shown in the BDC catalog
                "releaseStatus": "active",
                "visibility": "public",
            }
        ],
    }
}

bdc_connect_client.create_or_update_share(share_name, open_resource_discovery_information)
print("Share registered.")

# COMMAND ----------

# DBTITLE 1,Generate and upload the CSN schema
csn_schema = csn_generator.generate_csn_template(share_name)
print(f"CSN entities: {sorted(k for k, v in csn_schema['definitions'].items() if v.get('kind') == 'entity')}")

bdc_connect_client.create_or_update_share_csn(share_name, csn_schema)
print("CSN uploaded.")

# COMMAND ----------

# DBTITLE 1,Publish the data product
bdc_connect_client.publish_data_product(share_name)
print(f"Data product '{share_name}' published.")
