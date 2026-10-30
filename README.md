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
| Table names (= measurement fragments) | case-sensitive; table cache ignores case | case-sensitive | case-sensitive | not tested |
| Column names | case kept, matched case-insensitively | same | same | same (Spark default) |
| Equality deletes (`latest_inventory`) | yes | yes | yes | yes |
| Metadata caching | yes, refreshed in the background | yes, but 24 h by default (set to 60 s here) | none across sessions | per session |
| Data cache | on by default | off (needs a file-cache path) | none | none |
| Memory | allin1 under 3 GB | FE ~1.1 GB + BE ~2.2 GB | small | ~3 GB |
| Images | 5 GB | 14 GB | <1 GB + Grafana | 2.4 GB |

¹ 11 Grafana queries in parallel: 8 series, 24 hours, one device.

- **StarRocks:** fastest by a wide margin; one container; works with the defaults. Reads nested
  namespaces (dotted database names are split into levels); `init-catalog.sh` sets
  `iceberg.catalog.rest.nested-namespace-enabled` so `SHOW DATABASES` lists them too. Table
  names reach Polaris as written and resolve case-sensitively. Caveat: the table cache ignores
  case, so once `bearingTemperature` is loaded, `bearingtemperature` returns its data too instead
  of an error (a cold `bearingtemperature` fails). No wrong table is possible: Streaming Lake
  Ingestion gives a fragment that differs from an existing table only by case a numeric suffix
  (`CaseTest__88` next to `caseTest`, tested 2026-10-30).
- **Doris:** meets every requirement and keeps table names strictly case-sensitive, but slower,
  heavier and with surprising defaults. A tested alternative.
- **DuckDB:** fast for single ad-hoc queries (0.05 s warm), weak behind a dashboard: the Grafana
  plugin runs one query at a time and Iceberg metadata isn't cached across sessions.
- **Spark:** for batch and ETL; seconds of overhead per query, no maintained Grafana data source.
- **Dremio 26** (not benchmarked here): REST catalog source with vended credentials and nested
  namespaces, reads equality deletes (25 and earlier fail on `latest_inventory`). Matches table
  names case-insensitively.

- **Trino 484** (not benchmarked here): reads everything with
  `iceberg.rest-catalog.case-insensitive-name-matching=true` and
  `iceberg.rest-catalog.nested-namespace-enabled=true`, but lowercases all identifiers
  ([trinodb/trino#17](https://github.com/trinodb/trino/issues/17)), so names show as `casetest`
  and `eventtype`. Without the setting, mixed-case tables are unreachable. Name collisions can't
  happen: Streaming Lake Ingestion suffixes a table or column that differs from an existing one
  only by case (tested 2026-10-30: `CaseTest__88` next to `caseTest`, column `V__1` next to `v`).
  Starburst (Trino-based) is untested.

Ruled out:
- **Impala** (equality deletes only in the subset Flink writes; case-insensitive names),
  **Daft** (no equality deletes), **ClickHouse** (catalog integration experimental, position
  deletes only, no nested namespaces yet).

## Prerequisites

- Docker with Compose ≥ 2.20 (tested on Colima on macOS ARM64)
- Polaris catalog principal (OAuth2 client credentials), created with
  `POST https://<tenant-domain>/service/offloading/api/v1/principals/<NAME>`
  (needs `ROLE_OFFLOADING_ADMIN` or `ROLE_TENANT_ADMIN`; the secret is returned only once)
