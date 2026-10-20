# Databricks notebook source
# DBTITLE 1,Instructions
# MAGIC %md
# MAGIC ## Edit Polaris Iceberg S3 Secrets
# MAGIC
# MAGIC This notebook manages the `CumulocityPolarisIcebergS3` secret scope. The catalog uses credential vending, so no static AWS access/secret keys are stored; `aws_region` is an optional fallback. You can create the scope, edit individual secrets, or update all at once.
# MAGIC
# MAGIC **Instructions:**
# MAGIC 1. Run Cell 2 to create the widgets
# MAGIC 2. Select a secret from the `secret_to_edit` dropdown (or choose `ALL` to edit all)
# MAGIC 3. Enter the new value in the `secret_value` widget (ignored when `ALL` is selected)
# MAGIC 4. When `ALL` is selected, fill in the individual secret widgets that appear
# MAGIC 5. Run Cell 3 to store the secret(s)
# MAGIC 6. Run Cell 4 to list existing secrets in the scope
# MAGIC 7. Run Cell 5 to clean up widgets

# COMMAND ----------

# DBTITLE 1,Create input widgets
SECRET_KEYS = [
    "polaris_oauth_client_id",
    "polaris_oauth_client_secret",
    "polaris_oauth_token_url",
    "polaris_oauth_scope",
    "polaris_base_url",
    "polaris_warehouse",
    "aws_region",  # optional fallback; S3 credentials are vended by the catalog
]

# Dropdown to select which secret to edit
dbutils.widgets.dropdown("secret_to_edit", "ALL", ["ALL"] + SECRET_KEYS, "Secret to edit")

# Text widget for the new value (used when editing a single secret)
dbutils.widgets.text("secret_value", "", "New value")

# Individual secret widgets (used when ALL is selected)
for key in SECRET_KEYS:
    dbutils.widgets.text(key, "", key)

print("Widgets created.")
print("  - To edit ONE secret: select it from 'secret_to_edit' and enter the value in 'secret_value'.")
print("  - To edit ALL secrets: leave 'secret_to_edit' as 'ALL' and fill in the individual widgets.")

# COMMAND ----------

# DBTITLE 1,Store secret(s)
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import ResourceAlreadyExists

w = WorkspaceClient()

SCOPE = "CumulocityPolarisIcebergS3"

# Create scope if it doesn't exist
try:
    w.secrets.create_scope(scope=SCOPE)
    print(f"Scope '{SCOPE}' created.")
except ResourceAlreadyExists:
    print(f"Scope '{SCOPE}' already exists, continuing...")

SECRET_KEYS = [
    "polaris_oauth_client_id",
    "polaris_oauth_client_secret",
    "polaris_oauth_token_url",
    "polaris_oauth_scope",
    "polaris_base_url",
    "polaris_warehouse",
    "aws_region",  # optional fallback; S3 credentials are vended by the catalog
]

selected = dbutils.widgets.get("secret_to_edit")

if selected == "ALL":
    # Store all secrets that have a non-empty value
    stored = 0
    for key in SECRET_KEYS:
        value = dbutils.widgets.get(key)
        if not value:
            print(f"  SKIPPED '{key}' (empty)")
            continue
        w.secrets.put_secret(scope=SCOPE, key=key, string_value=value)
        print(f"  STORED  '{key}'")
        stored += 1
    print(f"\nDone! {stored}/{len(SECRET_KEYS)} secrets saved to scope: {SCOPE}")
else:
    # Store a single secret
    value = dbutils.widgets.get("secret_value")
    if not value:
        print(f"ERROR: 'secret_value' is empty. Please enter the new value for '{selected}'.")
    else:
        w.secrets.put_secret(scope=SCOPE, key=selected, string_value=value)
        print(f"Secret '{selected}' updated in scope '{SCOPE}'.")

# COMMAND ----------

# DBTITLE 1,List existing secrets in scope
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
SCOPE = "CumulocityPolarisIcebergS3"

try:
    secret_list = w.secrets.list_secrets(scope=SCOPE)
    print(f"Secrets in scope '{SCOPE}':")
    for s in secret_list:
        print(f"  - {s.key}")
except Exception as e:
    print(f"Could not list secrets: {e}")

# COMMAND ----------

# DBTITLE 1,Cleanup widgets
dbutils.widgets.removeAll()
print("All widgets removed.")