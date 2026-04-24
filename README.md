# Streaming Lake Ingestion

Query Apache Iceberg tables managed in a [Polaris](https://polaris.apache.org/) catalog using [StarRocks](https://www.starrocks.io/) as the query engine and [Metabase](https://www.metabase.com/) as the BI frontend.

## Architecture

```
Metabase (port 3000)  [native StarRocks driver]
    └── StarRocks FE (port 9030)
            └── Polaris REST Catalog  (OAuth2 client-credentials)
                    └── S3  (static credentials, no credential vending)
```

## Prerequisites

- Docker with Compose ≥ 2.20 (tested on Colima on macOS ARM64)
- Polaris catalog with OAuth2 client credentials
- AWS S3 bucket and IAM credentials with read access

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

List available namespaces:

```bash
docker exec starrocks mysql -h 127.0.0.1 -P 9030 -u root -e "SHOW DATABASES FROM polaris;"
```

Query Iceberg tables (backtick-quote mixed-case names):

```sql
SELECT * FROM polaris.cdc_measurement.`c8y_Temperature`
```

> **Known limitation:** Namespaces or tables whose name **starts with `view`** cannot be queried from StarRocks due to a parser conflict with the SQL `VIEW` keyword. Rename them in Polaris (e.g. `view_measurement` → `measurement_view`) to work around this.

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
| StarRocks FE | 800 MB JVM      |
| StarRocks BE | 1.5 GB / 3 GB   |
| Metabase     | 1.5 GB / 2 GB   |

## Configuration Notes

### OAuth2
`POLARIS_CLIENT_CREDENTIAL` = `CLIENT_ID:CLIENT_SECRET`.  
The token endpoint is auto-derived as `{POLARIS_URI}/v1/oauth/tokens`.

### S3 — No Credential Vending
AWS keys are set directly on the external catalog (`iceberg.catalog.vended-credentials-enabled=false`). No IAM role or credential vending required.

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

