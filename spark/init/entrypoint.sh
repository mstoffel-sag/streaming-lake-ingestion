#!/bin/bash
# Generates spark-defaults.conf from environment variables, then starts the
# Spark Thrift Server (HiveServer2-compatible) in the foreground, reachable via
# JDBC on port 10000 (beeline, DBeaver, ...).
set -e

mkdir -p /tmp/spark-conf

cat > /tmp/spark-conf/spark-defaults.conf <<EOC
# Iceberg extensions
spark.sql.extensions                              org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions

# Polaris REST catalog
spark.sql.catalog.polaris                         org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.polaris.type                    rest
spark.sql.catalog.polaris.uri                     ${POLARIS_URI}
spark.sql.catalog.polaris.credential              ${POLARIS_CLIENT_CREDENTIAL}
spark.sql.catalog.polaris.scope                   ${POLARIS_SCOPE}
spark.sql.catalog.polaris.warehouse               ${POLARIS_WAREHOUSE}

# Polaris assumes the lake's IAM role and returns short-lived S3 credentials
# per table (credential vending); S3FileIO picks them up from loadTable.
spark.sql.catalog.polaris.header.X-Iceberg-Access-Delegation  vended-credentials
spark.sql.catalog.polaris.io-impl                 org.apache.iceberg.aws.s3.S3FileIO
spark.sql.catalog.polaris.client.region           ${AWS_REGION}

# Make polaris the default catalog so clients see schemas/tables directly
spark.sql.defaultCatalog                          polaris
EOC

# Add optional OAuth2 server URI if provided
if [ -n "${POLARIS_OAUTH2_SERVER_URI}" ]; then
  echo "spark.sql.catalog.polaris.oauth2-server-uri       ${POLARIS_OAUTH2_SERVER_URI}" \
    >> /tmp/spark-conf/spark-defaults.conf
fi

echo "[init] Spark config written to /tmp/spark-conf/spark-defaults.conf"
echo "[init] Starting Spark Thrift Server on port 10000..."

export SPARK_CONF_DIR=/tmp/spark-conf

# start-thriftserver.sh daemonizes by default; keep it in the foreground so the
# container stays alive and logs go to stdout.
export SPARK_NO_DAEMONIZE=true
exec /opt/spark/sbin/start-thriftserver.sh \
  --master "local[2]" \
  --driver-memory 1g \
  --conf "spark.hiveserver2.thrift.port=10000" \
  --conf "spark.hiveserver2.thrift.bind.host=0.0.0.0"
