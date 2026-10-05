#!/bin/bash
# Creates the Polaris external Iceberg catalog in StarRocks.
# Runs once after StarRocks FE is healthy (via depends_on condition).
# Environment variables are substituted by bash before the SQL is sent.
set -e

echo "[init] Creating Polaris external catalog in StarRocks..."

mysql -h starrocks -P 9030 -u root --connect-timeout=10 <<EOF
DROP CATALOG IF EXISTS polaris;

CREATE EXTERNAL CATALOG polaris
COMMENT 'Polaris Iceberg REST catalog (OAuth2, vended S3 credentials)'
PROPERTIES (
    "type"                                    = "iceberg",
    "iceberg.catalog.type"                    = "rest",
    "iceberg.catalog.uri"                     = "${POLARIS_URI}",
    "iceberg.catalog.warehouse"               = "${POLARIS_WAREHOUSE}",

    "iceberg.catalog.credential"              = "${POLARIS_CLIENT_CREDENTIAL}",
    "iceberg.catalog.scope"                   = "${POLARIS_SCOPE}",

    -- Polaris assumes the lake's IAM role and returns short-lived S3
    -- credentials scoped to each table's location; no AWS keys needed here.
    "iceberg.catalog.vended-credentials-enabled" = "true",

    "aws.s3.region"                           = "${AWS_REGION}"
);

SHOW CATALOGS;
SHOW DATABASES FROM polaris;
EOF

echo "[init] Done. Polaris catalog is ready."
