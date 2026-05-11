# Databricks notebook source
# DBTITLE 1,Instructions
# MAGIC %md
# MAGIC ## Create Polaris Iceberg S3 Secrets
# MAGIC
# MAGIC This notebook creates the `CumulocityPolarisIcebergS3` secret scope and stores all required secrets using the Databricks SDK.
# MAGIC
# MAGIC **Instructions:**
# MAGIC 1. Run Cell 2 to create input widgets
# MAGIC 2. Fill in all widget values at the top of the notebook
# MAGIC 3. Run Cell 3 to create the scope and store secrets
# MAGIC 4. Run Cell 4 to clean up widgets

# COMMAND ----------

# DBTITLE 1,Create input widgets
# Create input widgets for all secret values
secrets = [
    "polaris_oauth_client_id",
    "polaris_oauth_client_secret",
    "polaris_oauth_token_url",
    "polaris_oauth_scope",
    "polaris_base_url",
    "polaris_warehouse",
    "aws_access_key",
    "aws_secret_key",
    "aws_region",
]

for secret in secrets:
    dbutils.widgets.text(secret, "", secret)

print("Widgets created. Fill in the values above, then run the next cell.")

# COMMAND ----------

# DBTITLE 1,Create scope and store secrets
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

SCOPE = "CumulocityPolarisIcebergS3"

# Create scope (skip if already exists)
try:
    w.secrets.create_scope(scope=SCOPE)
    print(f"Scope '{SCOPE}' created.")
except Exception as e:
    if "RESOURCE_ALREADY_EXISTS" in str(e):
        print(f"Scope '{SCOPE}' already exists, continuing...")
    else:
        raise e

# Store each secret
secrets = [
    "polaris_oauth_client_id",
    "polaris_oauth_client_secret",
    "polaris_oauth_token_url",
    "polaris_oauth_scope",
    "polaris_base_url",
    "polaris_warehouse",
    "aws_access_key",
    "aws_secret_key",
    "aws_region",
]

for key in secrets:
    value = dbutils.widgets.get(key)
    if not value:
        print(f"WARNING: '{key}' is empty, skipping.")
        continue
    w.secrets.put_secret(scope=SCOPE, key=key, string_value=value)
    print(f"Secret '{key}' stored.")

print(f"\nDone! All secrets saved to scope: {SCOPE}")

# COMMAND ----------

# DBTITLE 1,Cleanup widgets
# Remove all widgets after secrets are stored
dbutils.widgets.removeAll()
print("All widgets removed.")
