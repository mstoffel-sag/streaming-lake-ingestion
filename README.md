# Streaming Lake Ingestion

Query Apache Iceberg tables managed in a [Polaris](https://polaris.apache.org/) catalog using [Metabase](https://www.metabase.com/) as the BI frontend.

Two query engines are available; pick one and switch any time.

| Engine | Best for | Metabase driver |
|--------|----------|-----------------|
| **Trino** (default) | Standard SQL, lower memory | Trino |
| **StarRocks** | High-performance analytics, MySQL-compatible | MySQL 8+ |

## Architecture

```
Metabase (port 3000)
    └── Trino (port 8080)  OR  StarRocks FE (port 9030)
            └── Polaris REST Catalog  (OAuth2 client-credentials)
                    └── S3  (static credentials, no credential vending)
```

## Prerequisites

- Docker with Compose ≥ 2.20 (tested on Colima on macOS ARM64)
- Polaris catalog with OAuth2 client credentials
- AWS S3 bucket and IAM credentials with read access

## Setup

1. Copy the example environment file and fill in your credentials:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your Polaris and S3 credentials.

3. Start the default (Trino) stack:

   ```bash
   docker compose up -d
   ```

   Metabase will be available at http://localhost:3000 once Trino is healthy (~30 s).

---

## Switching Query Engines

> Always stop the current stack before starting the other — container names overlap.

### → Switch to StarRocks

```bash
docker compose down
docker compose --env-file .env -f starrocks/docker-compose.yml up -d
```

On first start an init container automatically creates the `polaris` external catalog in StarRocks and exits.

### → Switch back to Trino

```bash
docker compose -f starrocks/docker-compose.yml down
docker compose up -d
```

Metabase data (saved questions, dashboards) persists across switches via the shared `metabase_data` Docker volume.

---

## Connecting Metabase

### Trino

Admin → Databases → Add database → **Trino**

| Field    | Value     |
|----------|-----------|
| Host     | `trino`   |
| Port     | `8080`    |
| Catalog  | `polaris` |
| Username | `trino`   |
| Password | *(blank)* |

### StarRocks

Admin → Databases → Add database → **MySQL**

| Field                                     | Value                                    |
|-------------------------------------------|------------------------------------------|
| Host                                      | `starrocks`                              |
| Port                                      | `9030`                                   |
| Database                                  | `information_schema`                     |
| Username                                  | `root`                                   |
| Password                                  | *(blank)*                                |
| Additional JDBC connection string options | `tinyInt1isBit=false&useSSL=false&useMysqlMetadata=true` |

Available namespaces:

```bash
docker exec starrocks mysql -h 127.0.0.1 -P 9030 -u root -e "SHOW DATABASES FROM polaris;"
```

> **Note:** Use just the namespace name (e.g. `cdc_measurement`) as the Database field — not `polaris.cdc_measurement`.

Then query Iceberg tables via the `polaris` catalog:
```sql
SELECT * FROM polaris.`polaris`.`cdc_measurement`
```

> **Note on case-sensitive table names:** Both Trino and StarRocks lowercase unquoted identifiers. Use backticks (StarRocks) or double-quotes (Trino) for mixed-case names.

---

## Project Structure

```
.
├── docker-compose.yml            # default stack (includes trino/)
├── .env                          # local secrets — never committed
├── .env.example                  # template for .env
├── trino/
│   ├── docker-compose.yml        # Trino + Metabase stack
│   └── etc/
│       ├── config.properties     # query memory limits
│       ├── jvm.config            # JVM heap (2 GB)
│       ├── node.properties
│       ├── log.properties
│       └── catalog/
│           └── polaris.properties  # REST catalog + OAuth2 + S3
└── starrocks/
    ├── docker-compose.yml        # StarRocks + Metabase stack
    ├── fe.conf                   # FE JVM heap (800 MB)
    ├── be.conf                   # BE memory limit (1.5 GB)
    └── init/
        └── init-catalog.sh       # creates polaris external catalog on first start
```

## Memory Budget (6 GB host)

| Container          | Heap / Limit     | Stack      |
|--------------------|------------------|------------|
| Trino              | 2 GB JVM / 3 GB  | trino      |
| Metabase           | 1.5 GB / 2 GB    | both       |
| StarRocks FE       | 800 MB JVM       | starrocks  |
| StarRocks BE       | 1.5 GB / 3 GB    | starrocks  |

## Configuration Notes

### OAuth2
Both engines use the Iceberg REST catalog client-credentials flow.  
`POLARIS_CLIENT_CREDENTIAL` = `CLIENT_ID:CLIENT_SECRET`.  
The token endpoint is auto-derived as `{POLARIS_URI}/v1/oauth/tokens`.

### S3 — No Credential Vending
Trino: `iceberg.rest-catalog.vended-credentials-enabled=false` — uses static AWS keys.  
StarRocks: AWS keys are set directly on the external catalog — credential vending is not used.

## Useful Commands

```bash
# Logs
docker compose logs -f
docker compose --env-file .env -f starrocks/docker-compose.yml logs -f

# Restart after config change
docker compose restart trino
docker compose --env-file .env -f starrocks/docker-compose.yml restart starrocks

# Stop everything
docker compose down
docker compose -f starrocks/docker-compose.yml down

# Full reset including volumes (resets Metabase)
docker compose down -v
```

