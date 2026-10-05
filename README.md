# Streaming Lake Ingestion

Query Apache Iceberg tables managed in a [Polaris](https://polaris.apache.org/) catalog using [StarRocks](https://www.starrocks.io/) as the query engine and [Metabase](https://www.metabase.com/) as the BI frontend.

## Architecture

```
Metabase (port 3000)  [native StarRocks driver]
    └── StarRocks FE (port 9030)
            └── Polaris REST Catalog  (OAuth2 client-credentials)
                    └── S3  (short-lived credentials vended by Polaris per table)
```

## Prerequisites

- Docker with Compose ≥ 2.20 (tested on Colima on macOS ARM64)
- StarRocks 4.1.6 (pinned in `docker-compose.yml`)
- Polaris catalog principal (OAuth2 client credentials), created with
  `POST https://<tenant-domain>/service/offloading/api/v1/principals/<NAME>`
  (needs `ROLE_OFFLOADING_ADMIN` or `ROLE_TENANT_ADMIN`; the secret is returned only once)

## Setup

```bash
cd starrocks
cp .env.example .env   # fill in your credentials
docker compose up -d
```

Metabase will be available at http://localhost:3000 once StarRocks is healthy (~90 s).

---

## Connecting Metabase

Admin → Databases → Add database → **StarRocks**

| Field    | Value       |
|----------|-------------|
| Host     | `starrocks` |
| Port     | `9030`      |
| Catalog  | `polaris`   |
| Database | *(blank — shows all namespaces)* |
| Username | `root`      |
| Password | *(blank)*   |

The native StarRocks driver ([Carbon-Arc/metabase-starrocks-driver](https://github.com/Carbon-Arc/metabase-starrocks-driver)) is baked into the Metabase image automatically via `Dockerfile.metabase`.
`Dockerfile.metabase` pins Metabase `v0.63.19.1` and driver `v1.2.0` — driver `v1.0.2` fails on
Metabase 0.63 with `Syntax error compiling at (metabase/driver/starrocks.clj:239:1)`.
Metabase keeps its own H2 file `metabase-starrocks.db` in the shared `metabase_data` volume.

List available namespaces:

```bash
docker exec starrocks mysql -h 127.0.0.1 -P 9030 -u root -e "SHOW DATABASES FROM polaris;"
```

Query Iceberg tables. Mixed-case names keep their case and are matched case-insensitively,
so both of these work; backticks are only required for names with special characters such as `-`:

```sql
SELECT * FROM polaris.cdc_measurement.`c8y_Temperature`;
SELECT * FROM polaris.cdc_measurement.c8y_temperature;
SELECT * FROM polaris.cdc_measurement.`cgroup-mosquitto`;
```

The `view_*` namespaces hold Iceberg views with flattened columns and are queryable
since StarRocks 4.1 (earlier versions failed on names starting with `view`):

```sql
SELECT * FROM polaris.view_measurement.`c8y_serverResponseTime`;
```

---

## Project Structure

```
starrocks/                        ← work from this directory
├── docker-compose.yml            # StarRocks + Metabase stack
├── Dockerfile.metabase           # Metabase + StarRocks driver baked in
├── .env                          # local secrets — never committed
├── .env.example                  # template for .env
└── init/
    └── init-catalog.sh           # creates polaris external catalog on first start
```

## Memory Budget (6 GB host)

| Container    | Heap / Limit    |
|--------------|-----------------|
| StarRocks FE | 1 GB JVM heap (`fe.conf`; the image default is 8 GB) |
| StarRocks BE | 1.5 GB (`be.conf`, `mem_limit = 1500M` — the unit is `M`, `MB` crashes the BE) |
| Metabase     | 1.5 GB / 2 GB   |

`fe.conf` and `be.conf` are the image's own files with only these memory settings changed;
they are mounted over the defaults. Give the Docker VM at least 6 GB
(`colima start --memory 6`) — with 2 GB the FE is OOM-killed while the container still
reports healthy.

## Configuration Notes

### OAuth2
`POLARIS_CLIENT_CREDENTIAL` = `CLIENT_ID:CLIENT_SECRET`.  
The token endpoint is auto-derived as `{POLARIS_URI}/v1/oauth/tokens`.

### S3 — Credential Vending
No AWS keys are configured. With `iceberg.catalog.vended-credentials-enabled=true`, Polaris
assumes the data lake's IAM role and returns STS credentials scoped to each table's location;
StarRocks refreshes them in the background. Only `AWS_REGION` (the bucket's region) is needed.

## Useful Commands

All commands must be run from the `starrocks/` directory.

```bash
# Logs
docker compose logs -f

# Restart StarRocks after config change
docker compose restart starrocks

# Re-register the Polaris catalog (e.g. after credentials change)
docker compose run --rm starrocks-init

# Stop everything
docker compose down

# Full reset including volumes (resets Metabase + catalog)
docker compose down -v

# Rebuild Metabase image (e.g. after driver version bump)
docker compose build metabase
```

