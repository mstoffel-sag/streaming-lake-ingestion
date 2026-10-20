# Spark

Spark Thrift Server (HiveServer2) with the Polaris catalog as default catalog. Polaris vends
short-lived S3 credentials per table, so no AWS keys are stored.

```
JDBC client (beeline, DBeaver, ...)  jdbc:hive2://localhost:10000
    └── Spark 4.1.3 + Iceberg 1.12.0
            └── Polaris REST Catalog  (OAuth2 client-credentials)
                    └── S3  (vended credentials)
```

## Setup

```bash
cd spark
cp .env.example .env   # fill in the Polaris credentials
docker compose up -d
docker exec -it spark-thrift /opt/spark/bin/beeline -u jdbc:hive2://localhost:10000
SHOW NAMESPACES;
SELECT source, time, bearingTemperature.value FROM cdc_measurement.bearingTemperature
ORDER BY time DESC LIMIT 5;
```

Spark UI: http://localhost:4040

## Notes

- No Grafana here: Grafana has no maintained Spark/HiveServer2 data source, and Kyuubi's MySQL
  frontend (the other route) was removed in Kyuubi 1.12. Use `starrocks/` or `duckdb/` for dashboards.
- Iceberg 1.7.x fails on vended credentials with `Target host is not specified`; 1.10+ works.
- Iceberg has no runtime for Spark 4.2 yet, hence Spark 4.1.
- `iceberg-aws-bundle` provides the AWS SDK for `S3FileIO`; the Spark image has none.
