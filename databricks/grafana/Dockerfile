FROM grafana/grafana:13.2.4

# Community Databricks data source (Grafana's own Databricks plugin needs Enterprise/Cloud).
# Installed from the GitHub release; it is not in the Grafana plugin catalog.
ARG PLUGIN_VERSION=1.3.8
ARG PLUGIN_URL=https://github.com/mullerpeter/databricks-grafana/releases/download/v${PLUGIN_VERSION}/mullerpeter-databricks-datasource.zip

USER root
RUN mkdir -p /opt/grafana-plugins \
    && wget -q -O /tmp/plugin.zip "${PLUGIN_URL}" \
    && unzip -q /tmp/plugin.zip -d /opt/grafana-plugins \
    && rm /tmp/plugin.zip \
    && chown -R grafana /opt/grafana-plugins
USER grafana

# Outside /var/lib/grafana, so the grafana_data volume doesn't hide it
ENV GF_PATHS_PLUGINS=/opt/grafana-plugins \
    GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=mullerpeter-databricks-datasource
