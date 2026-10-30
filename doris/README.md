# Doris

Query the Polaris catalog with [Apache Doris](https://doris.apache.org/) 4.1.5 and chart
measurements in Grafana. Polaris vends short-lived S3 credentials per table, so no AWS keys
are stored.

```
Grafana (port 3000)  [MySQL data source]
    └── Doris FE (port 9030) + BE
            └── Polaris REST Catalog  (OAuth2 client-credentials)
                    └── S3  (vended credentials)
```

```bash
cp .env.example .env   # fill in your credentials
docker compose up -d
python3 init/device_series.py   # once, after doris-init has finished
```

Grafana: **http://localhost:3000** (user `admin`). The **Cumulocity / Measurements** dashboard
and the views behind it (`measurements.device_series`, a materialized view refreshed every
10 minutes, and `measurements.series_values`) work like in `starrocks/`; the dashboard is the
same apart from the data source.

SQL: `docker exec -it doris-fe mysql -h 127.0.0.1 -P 9030 -u root`, tables as
`polaris.<namespace>.<table>`, e.g. `polaris.cdc_measurement.bearingTemperature`.

## Tested against the tenant (2026-10-20)

| Check | Result |
|---|---|
| Vended credentials | works |
| Table / namespace names | case-sensitive: `bearingTemperature` works, `bearingtemperature` is not found (StarRocks too, until `bearingTemperature` is in its case-insensitive table cache) |
| Column / struct field names | case kept, but matched case-insensitively (`lastupdated` finds `lastUpdated`), like StarRocks, DuckDB and Spark |
| Equality deletes | `latest_inventory.inventory` returns one row per id (28,138, same as Spark) |
| Nested namespaces | listed as `default.t15264971`, `default.t15264971.internal` (StarRocks lists them too since `iceberg.catalog.rest.nested-namespace-enabled` is set; DuckDB and Spark don't show them) |
| Full dashboard, 11 queries in parallel (8 series, 24 h) | 20.5 s cold, 11–12 s warm (StarRocks 18.2 s / 3.0 s, DuckDB 24.6 s / 9.1 s) |

## Notes

- **Memory:** Doris needs more than the other stacks: FE ~1.1 GB (heap lowered from 8 GB to
  1 GB in the entrypoint), BE ~2.2 GB at rest, so the BE gets `mem_limit = 3G`. With less, it
  cancels queries with `MEM_LIMIT_EXCEEDED` under dashboard load. Tested in an 8 GB Colima VM.
- **Disk:** the BE image alone is 9.6 GB (FE 4.2 GB).
- **Metadata cache:** Doris caches table and snapshot metadata for 24 h by default, so
  queries keep reading an old snapshot. `init/init-catalog.sh` sets 60 s and enables the
  manifest cache (off by default).
- **Why it's slower than StarRocks:** every query reads all data files of a table from S3
  (the CDC tables aren't partitioned; 24 small files for `bearingTemperature`). StarRocks
  keeps them in its local Data Cache. Doris has a file cache too, but it needs a
  `file_cache_path` on the BE and disk space; it isn't configured here.
- **Docker networking:** `FE_SERVERS` / `BE_ADDR` need fixed IPs (172.30.80.2/.3); dynamic
  addresses are limited to `172.30.80.128/25` so `doris-init` can't take the BE's address.
- `SELECT 1` already needs a BE, so the FE healthcheck uses `SHOW FRONTENDS`.
