#!/bin/bash
# Waits for the Doris BE to register, then creates the Polaris Iceberg catalog.
# Runs once after the FE is healthy (via depends_on condition).
set -e

MYSQL=(mysql -h fe -P 9030 -u root --connect-timeout=10)

# Doris adds the BE from FE_SERVERS/BE_ADDR; queries fail until it reports Alive
echo "[init] Waiting for the Doris BE..."
for _ in $(seq 1 60); do
  "${MYSQL[@]}" -N -e "SHOW BACKENDS" 2>/dev/null | grep -qw true && break
  sleep 5
done
"${MYSQL[@]}" -N -e "SHOW BACKENDS" | grep -qw true || { echo "[init] BE not alive"; exit 1; }

echo "[init] Creating Polaris external catalog in Doris..."
"${MYSQL[@]}" <<EOF
DROP CATALOG IF EXISTS polaris;

CREATE CATALOG polaris
COMMENT 'Polaris Iceberg REST catalog (OAuth2, vended S3 credentials)'
PROPERTIES (
    'type'                                    = 'iceberg',
    'iceberg.catalog.type'                    = 'rest',
    'iceberg.rest.uri'                        = '${POLARIS_URI}',
    'warehouse'                               = '${POLARIS_WAREHOUSE}',

    'iceberg.rest.security.type'              = 'oauth2',
    'iceberg.rest.oauth2.credential'          = '${POLARIS_CLIENT_CREDENTIAL}',
    'iceberg.rest.oauth2.server-uri'          = '${POLARIS_OAUTH2_SERVER_URI}',
    'iceberg.rest.oauth2.scope'               = '${POLARIS_SCOPE}',

    -- Polaris assumes the lake's IAM role and returns short-lived S3
    -- credentials scoped to each table's location; no AWS keys needed here.
    'iceberg.rest.vended-credentials-enabled' = 'true',
    'iceberg.rest.nested-namespace-enabled'   = 'true',
    's3.region'                               = '${AWS_REGION}',

    -- Table/snapshot metadata is cached for 24 h by default, so queries keep
    -- reading an old snapshot; 60 s keeps dashboards current. Manifests never
    -- change once written, so caching them long is safe (off by default).
    'meta.cache.iceberg.table.ttl-second'     = '60',
    'meta.cache.iceberg.snapshot.ttl-second'  = '60',
    'meta.cache.iceberg.manifest.enable'      = 'true',
    'meta.cache.iceberg.manifest.ttl-second'  = '86400'
);

SHOW DATABASES FROM polaris;
EOF

echo "[init] Done. Polaris catalog is ready."
