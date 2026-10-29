FROM grafana/grafana:13.2.4

# Community Snowflake data source by Michelin (Grafana's own Snowflake plugin needs Enterprise/Cloud).
# Installed from the GitHub release; it is not signed.
ARG PLUGIN_VERSION=2.1.0
ARG PLUGIN_URL=https://github.com/michelin/snowflake-grafana-datasource/releases/download/v${PLUGIN_VERSION}/snowflake-grafana-datasource.zip

USER root
RUN mkdir -p /opt/grafana-plugins \
    && wget -q -O /tmp/plugin.zip "${PLUGIN_URL}" \
    && unzip -q /tmp/plugin.zip -d /opt/grafana-plugins \
    && rm /tmp/plugin.zip \
    && chown -R grafana /opt/grafana-plugins
USER grafana

# Outside /var/lib/grafana, so the grafana_data volume doesn't hide it
ENV GF_PATHS_PLUGINS=/opt/grafana-plugins \
    GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=michelin-snowflake-datasource
