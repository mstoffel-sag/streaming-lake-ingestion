# Streaming Lake Ingestion

Query Apache Iceberg tables managed in a [Polaris](https://polaris.apache.org/) catalog using [Trino](https://trino.io/) as the query engine and [Metabase](https://www.metabase.com/) as the BI frontend.

## Architecture

```
Metabase (port 3000)
    └── Trino (port 8080)
            └── Polaris REST Catalog (OAuth2 client-credentials)
                    └── S3 (static credentials, no credential vending)
```

## Prerequisites

- Docker with Compose (tested on Colima on macOS ARM64)
- Polaris catalog with OAuth2 client credentials
- AWS S3 bucket and IAM credentials with read access

## Setup

1. Copy the example environment file and fill in your credentials:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your Polaris and S3 credentials.

3. Start the stack:

   ```bash
   docker compose up -d
   ```

   Trino starts first; Metabase waits until Trino is healthy (~30 seconds).

4. Open Metabase at http://localhost:3000 and complete the initial setup.

## Connecting Metabase to Trino

In Metabase → **Admin → Databases → Add database**:

| Field    | Value       |
|----------|-------------|
| Type     | Trino       |
| Host     | `trino`     |
| Port     | `8080`      |
| Catalog  | `polaris`   |
| Username | `trino`     |
| Password | *(blank)*   |

## Project Structure

```
.
├── docker-compose.yml
├── .env                      # local secrets — never committed
├── .env.example              # template for .env
└── trino/
    └── etc/
        ├── config.properties # Trino server config (memory limits)
        ├── jvm.config        # JVM heap settings (2 GB)
        ├── node.properties
        ├── log.properties
        └── catalog/
            └── polaris.properties  # Iceberg REST catalog + OAuth2 + S3
```

## Configuration Notes

### OAuth2
Trino uses the client-credentials flow. Set `POLARIS_CLIENT_CREDENTIAL` as `client_id:client_secret` in `.env`. The token endpoint is derived automatically from `POLARIS_URI` (`/v1/oauth/tokens`).

### S3 — No Credential Vending
Credential vending from Polaris is disabled (`iceberg.rest-catalog.vended-credentials-enabled=false`). Trino authenticates directly to S3 using `AWS_ACCESS_KEY` / `AWS_SECRET_KEY`.

### Memory (6 GB host)
| Container | Heap / Limit |
|-----------|-------------|
| Trino     | 2 GB JVM / 3 GB container |
| Metabase  | 1.5 GB JVM / 2 GB container |

## Useful Commands

```bash
# View logs
docker compose logs -f

# Restart Trino only (e.g. after config change)
docker compose restart trino

# Stop everything
docker compose down

# Stop and remove volumes (resets Metabase)
docker compose down -v
```
