# Streaming Lake Ingestion — connection examples

Examples of how to connect query engines and data platforms to
[Cumulocity Streaming Lake Ingestion](https://cumulocity.com/docs/datahub/streaming-lake-ingestion/#overview).
Streaming Lake Ingestion continuously writes a tenant's inventory, measurements, events, alarms
and operations as Apache Iceberg tables to a data lake and exposes them through an Iceberg REST
catalog ([Polaris](https://polaris.apache.org/)). Each directory below shows one way to read that
catalog, from local Docker stacks with Grafana dashboards to Snowflake and Databricks.

These are examples, not production setups: they are tested against one tenant and tuned for a
laptop. Every example uses Polaris **credential vending**: Polaris assumes the data lake's IAM
role and hands out short-lived S3 credentials per table, so no AWS keys are configured anywhere.

| Directory | Engine | Dashboards |
|---|---|---|
| `starrocks/` | StarRocks 4.1.6 ([README](starrocks/README.md)) | Grafana (MySQL data source) |
| `doris/` | Apache Doris 4.1.5 ([README](doris/README.md)) | Grafana (MySQL data source) |
| `duckdb/` | DuckDB 1.5.6 `iceberg` extension ([README](duckdb/README.md)) | Grafana (DuckDB plugin) |
| `spark/` | Spark 4.1.3 Thrift Server + Iceberg 1.12.0 ([README](spark/README.md)) | none (JDBC only) |
| `snowflake/` | Snowflake catalog-linked database, SAP BDC data product ([README](snowflake/README.md)) | Grafana (community Snowflake plugin, key pair) |
| `databricks/` | Incremental import into Delta ([README](databricks/README.md)) | Grafana (community Databricks plugin, SQL warehouse) |
| `aws/` | `setup-c8y-streaming-lake-role.sh`: S3 bucket and IAM role for an own data lake | — |

`starrocks/`, `doris/`, `duckdb/`, `databricks/grafana/` and `snowflake/grafana/` all serve Grafana on port 3000 (the last two: `GRAFANA_PORT`); run one of them at a time or set different ports.

## Engine comparison

**StarRocks is the recommended engine for dashboards.** All results below are from one
Cumulocity tenant (167 tables), tested 2026-10-20 in an 8 GB Colima VM.

| | StarRocks | Doris | DuckDB | Spark |
|---|---|---|---|---|
| Measurements dashboard, warm¹ | **3 s** | 11–12 s | 9 s | no Grafana |
| Same, right after a start¹ | 18 s | 20 s | 25 s | — |
| Table names (= measurement fragments) | case kept, **matched case-insensitively** | case-sensitive | case-sensitive | not tested |
| Column names | case kept, matched case-insensitively | same | same | same (Spark default) |
| Equality deletes (`latest_inventory`) | yes | yes | yes | yes |
| Metadata caching | yes, refreshed in the background | yes, but 24 h by default (set to 60 s here) | none across sessions | per session |
| Data cache | on by default | off (needs a file-cache path) | none | none |
| Memory | allin1 under 3 GB | FE ~1.1 GB + BE ~2.2 GB | small | ~3 GB |
| Images | 5 GB | 14 GB | <1 GB + Grafana | 2.4 GB |

¹ 11 Grafana queries in parallel: 8 series, 24 hours, one device.

- **StarRocks:** fastest by a wide margin; one container; works with the defaults. Caveat: it
  resolves table names case-insensitively (`bearingtemperature` finds `bearingTemperature`). What
  happens if two fragment tables ever differ only by case is untested.
- **Doris:** meets every requirement, keeps table names strictly case-sensitive and is the only
  engine that lists the catalog's nested namespaces, but slower, heavier and with surprising defaults. A tested alternative.
- **DuckDB:** fast for single ad-hoc queries (0.05 s warm), weak behind a dashboard: the Grafana
  plugin runs one query at a time and Iceberg metadata isn't cached across sessions.
- **Spark:** for batch and ETL; seconds of overhead per query, no maintained Grafana data source.

Ruled out:
- **Trino / Starburst:** lowercase all identifiers
  ([trinodb/trino#17](https://github.com/trinodb/trino/issues/17), open since 2019). The
  `case-insensitive-name-matching` workaround fails once two fragments differ only by case,
  and Cumulocity fragment names must stay case-sensitive.
- **Impala** (no equality deletes), **Daft** (no equality deletes), **ClickHouse** (catalog
  integration experimental, no nested namespaces yet), **Dremio** (REST catalog source not in
  the open-source edition).

## Prerequisites

- Docker with Compose ≥ 2.20 (tested on Colima on macOS ARM64)
- Polaris catalog principal (OAuth2 client credentials), created with
  `POST https://<tenant-domain>/service/offloading/api/v1/principals/<NAME>`
  (needs `ROLE_OFFLOADING_ADMIN` or `ROLE_TENANT_ADMIN`; the secret is returned only once)
