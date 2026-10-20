# StarRocks

Query the Polaris catalog with [StarRocks](https://www.starrocks.io/) 4.1.6 and chart measurements
in Grafana. Polaris vends short-lived S3 credentials per table, so no AWS keys are stored.

```
Grafana (port 3000)  [MySQL data source]
    └── StarRocks FE (port 9030)
            └── Polaris REST Catalog  (OAuth2 client-credentials)
                    └── S3  (short-lived credentials vended by Polaris per table)
```

```bash
cp .env.example .env   # fill in your credentials
docker compose up -d
python3 init/device_series.py   # once, after StarRocks is healthy (~90 s)
```

## Grafana — measurements over time

Grafana runs at **http://localhost:3000** (user `admin`, password `GRAFANA_ADMIN_PASSWORD` from
`.env`). The data source (Grafana's MySQL plugin against `starrocks:9030`) and the
**Cumulocity / Measurements** dashboard are provisioned from `grafana/`; the dashboard
is also the home page.

Pick a **Device**, then one or more **Series** (multi-select, with *All*; only that
device's series are offered), and use the normal Grafana time picker. Panels: all selected
series in one chart (`$__timeGroupAlias` averages to the panel width), per-series latest /
min / avg / max / count, the latest 200 values, all series of the device, and one chart
per series (a repeated panel, for series whose scales differ). Panels take ≈0.3–0.8 s.

Two StarRocks views behind it, both created by `init/device_series.py`:

- `measurements.device_series`: a materialized view, one row per device and series,
  refreshed every 10 minutes. Feeds the device and series lists. Device labels are
  `name · id` (names are not unique); devices missing from `latest_inventory.inventory`
  show only their ID.
- `measurements.series_values`: a plain view, every series as `time, source, metric,
  value, unit` (a `UNION ALL` over the fragment tables). Each branch carries its metric as a
  constant, so `WHERE metric IN (...)` prunes all other branches and StarRocks scans only
  the tables of the selected series.

Run the script once after the first start and again when new measurement **types or
series** appear (new devices and values are picked up automatically). The views live in the
`fe_meta` / `be_storage` volumes, so they survive container restarts.

## SQL

```bash
docker exec -it starrocks mysql -h 127.0.0.1 -P 9030 -u root
SHOW DATABASES FROM polaris;
```

Mixed-case names keep their case and are matched case-insensitively, so both of these work;
backticks are only required for names with special characters such as `-`:

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

## Project structure

```
starrocks/                        ← run everything from here
├── docker-compose.yml            # StarRocks + Grafana stack
├── fe.conf, be.conf              # image defaults with smaller memory settings
├── .env                          # local secrets — never committed
├── .env.example                  # template for .env
├── grafana/                      # provisioned data source and dashboard
└── init/
    ├── init-catalog.sh           # creates polaris external catalog on first start
    └── device_series.py          # creates the measurements views for Grafana
```

## Memory budget (6 GB host)

| Container    | Heap / Limit    |
|--------------|-----------------|
| StarRocks FE | 1 GB JVM heap (`fe.conf`; the image default is 8 GB) |
| StarRocks BE | 1.5 GB (`be.conf`, `mem_limit = 1500M` — the unit is `M`, `MB` crashes the BE) |
| Grafana      | 768 MB          |

`fe.conf` and `be.conf` are the image's own files with only these memory settings changed;
they are mounted over the defaults. Give the Docker VM at least 6 GB
(`colima start --memory 6`) — with 2 GB the FE is OOM-killed while the container still
reports healthy.

## Configuration notes

- **OAuth2:** `POLARIS_CLIENT_CREDENTIAL` = `CLIENT_ID:CLIENT_SECRET`. The token endpoint is
  auto-derived as `{POLARIS_URI}/v1/oauth/tokens`.
- **Credential vending:** with `iceberg.catalog.vended-credentials-enabled=true`, StarRocks
  gets STS credentials scoped to each table's location and refreshes them in the background.
  Only `AWS_REGION` (the bucket's region) is needed.

## Useful commands

```bash
docker compose logs -f                      # logs
docker compose restart starrocks            # after a config change
docker compose run --rm starrocks-init      # re-register the catalog (e.g. new credentials)
docker compose down                         # stop everything
docker compose down -v                      # full reset including volumes (catalog, views, Grafana)
```
