#!/bin/bash
# Initialises the DuckDB database file with a persistent secret for the Polaris
# Iceberg REST catalog, verifies the catalog is attachable and builds the
# measurement views for Grafana.
# Runs once after the duckdb container is healthy (via depends_on condition).
set -e

DB_FILE=/data/main.duckdb
RC_FILE=/data/duckdbrc.sql

echo "[init] Configuring DuckDB persistent secret for Polaris..."

duckdb "${DB_FILE}" <<EOF
INSTALL iceberg;
LOAD iceberg;
INSTALL httpfs;
LOAD httpfs;

-- Polaris OAuth2 client-credentials secret. No S3 secret: Polaris assumes the
-- lake's IAM role and vends short-lived S3 credentials per table.
CREATE OR REPLACE PERSISTENT SECRET polaris_oauth (
    TYPE ICEBERG,
    CLIENT_ID '${POLARIS_CLIENT_ID}',
    CLIENT_SECRET '${POLARIS_CLIENT_SECRET}',
    OAUTH2_SERVER_URI '${POLARIS_OAUTH2_SERVER_URI}',
    OAUTH2_SCOPE '${POLARIS_SCOPE}'
);
DROP PERSISTENT SECRET IF EXISTS s3_secret;
EOF

# DuckDB does not persist ATTACH metadata across sessions for REST catalogs,
# so emit a startup script that every CLI session can run.
cat > "${RC_FILE}" <<EOF
INSTALL iceberg;
LOAD iceberg;
INSTALL httpfs;
LOAD httpfs;
-- Path-style S3 URLs: virtual-hosted ones fail TLS for bucket names with dots
SET s3_url_style = 'path';
ATTACH IF NOT EXISTS '${POLARIS_WAREHOUSE}' AS polaris (
    TYPE ICEBERG,
    ENDPOINT '${POLARIS_URI}',
    ACCESS_DELEGATION_MODE 'vended_credentials'
);
EOF

echo "[init] Verifying catalog attach..."
duckdb "${DB_FILE}" -init "${RC_FILE}" -c "SHOW DATABASES;"

echo "[init] Building measurement views for Grafana..."
python3 /init/measurement_views.py

echo "[init] Done. Persistent secret stored; startup SQL at ${RC_FILE}."
