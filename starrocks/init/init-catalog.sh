#!/bin/bash
# Creates the Polaris external Iceberg catalog in StarRocks.
# Runs once after StarRocks FE is healthy (via depends_on condition).
# Environment variables are substituted by bash before the SQL is sent.
set -e

echo "[init] Creating Polaris external catalog in StarRocks..."

mysql -h starrocks -P 9030 -u root --connect-timeout=10 <<EOF
DROP CATALOG IF EXISTS polaris;

CREATE EXTERNAL CATALOG polaris
COMMENT 'Polaris Iceberg REST catalog (OAuth2, static S3 credentials)'
PROPERTIES (
    "type"                                    = "iceberg",
    "iceberg.catalog.type"                    = "rest",
    "iceberg.catalog.uri"                     = "${POLARIS_URI}",
    "iceberg.catalog.warehouse"               = "${POLARIS_WAREHOUSE}",

    "iceberg.catalog.credential"              = "${POLARIS_CLIENT_CREDENTIAL}",
    "iceberg.catalog.scope"                   = "${POLARIS_SCOPE}",

    "iceberg.catalog.vended-credentials-enabled" = "false",

    "aws.s3.use_instance_profile"             = "false",
    "aws.s3.access_key"                       = "${AWS_ACCESS_KEY}",
    "aws.s3.secret_key"                       = "${AWS_SECRET_KEY}",
    "aws.s3.region"                           = "${AWS_REGION}"
);

SHOW CATALOGS;
EOF

echo "[init] Done. Polaris catalog is ready."
