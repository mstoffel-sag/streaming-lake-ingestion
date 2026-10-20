# Snowflake

Query the Cumulocity Iceberg tables from Snowflake through a catalog-linked database on the
Polaris REST catalog. Data stays in Cumulocity storage; Snowflake reads it with credentials
vended by Polaris.

```
Snowflake
    ├── CUMULOCITY_<T>          CURATED.DEVICE_LATEST / ALARM_LATEST (dynamic tables), OPS (task, alert)
    └── CUMULOCITY_ICEBERG_<T>  catalog-linked, read-only
            └── Polaris REST Catalog  (OAuth2 client credentials)
                    └── S3  (vended credentials)
```

## Notebooks

Import them into Snowsight (Projects → Notebooks → Import .ipynb). They use `%%sql` cells and
the Snowpark session, so they run as Snowflake Notebooks, not in a local Jupyter.

| Notebook | Purpose |
|---|---|
| `cumulocity_build_up.ipynb` | Creates everything for one tenant: warehouse, catalog integration, linked database, curated dynamic tables, schema-change task, optional e-mail alert |
| `cumulocity_query_examples.ipynb` | Read-only queries: devices, alarms, measurements, events, device timeline |
| `cumulocity_tear_down.ipynb` | Removes all objects of one tenant (irreversible) |

All object names end with the tenant ID, so several tenants can share one account.

## Prerequisites

- Snowflake account with `ACCOUNTADMIN`
- Polaris catalog principal (OAuth2 client credentials), see
  [Obtaining Iceberg catalog credentials](https://cumulocity.com/docs/datahub/streaming-lake-ingestion/#obtaining-iceberg-catalog-credentials)
- For alerting: a verified e-mail of a user in the account

## Usage

1. In `cumulocity_build_up.ipynb`, set `catalog_host`, `catalog_name` (tenant ID),
   `oauth_client_id`, `oauth_client_secret` and optionally `alert_email`, then run top to bottom.
2. Re-run the sync cells in section 3 until the CDC tables show snapshots.
3. Query `CUMULOCITY_<T>.CURATED.*` and `CUMULOCITY_ICEBERG_<T>."cdc_measurement"."<series>"`.

The OAuth secret is stored in plain text in the notebook (a catalog integration only accepts a
literal secret). Clear it before exporting or committing the notebook.

## Notes

- `latest_inventory` tables can't be read in Snowflake (Iceberg equality deletes are
  unsupported); `DEVICE_LATEST` and `ALARM_LATEST` are derived from the CDC logs instead and
  refresh incrementally (target lag 5 min).
- A serverless task checks every 15 min for column changes in `cdc_inventory` / `cdc_alarm`
  and rebuilds the dynamic tables when the schema evolves.
