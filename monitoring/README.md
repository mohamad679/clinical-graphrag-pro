# Monitoring Stack

Clinical GraphRAG Pro exposes Prometheus-compatible metrics from the backend at `/metrics`. This directory adds a Prometheus + Grafana overlay that can be started alongside the main application stack.

## Quick Start

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

## Access

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001

Default Grafana credentials:

- Username: `admin`
- Password: `clinical_grafana_2025`

## Dashboard

The default dashboard is provisioned automatically from:

- [`monitoring/grafana/dashboards/clinical-graphrag.json`](./grafana/dashboards/clinical-graphrag.json)

Grafana will load it on startup and set it as the home dashboard through `GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH`.

## Import Additional Dashboards

You can add more dashboards in either of these ways:

1. Copy another dashboard JSON file into `monitoring/grafana/dashboards/` and restart Grafana.
2. Import a dashboard through the Grafana UI, then export the JSON back into `monitoring/grafana/dashboards/` if you want to keep it under version control.

The provisioning provider is configured in:

- [`monitoring/grafana/provisioning/dashboards/default.yml`](./grafana/provisioning/dashboards/default.yml)

The default Prometheus datasource is configured in:

- [`monitoring/grafana/provisioning/datasources/prometheus.yml`](./grafana/provisioning/datasources/prometheus.yml)

## Notes

- The monitoring overlay expects the default Compose network name `clinical-graphrag-pro_default`.
- If you launch the main stack with a custom Compose project name, update the external network name in `docker-compose.monitoring.yml` accordingly.
- The dashboard uses the metrics currently emitted by `backend/app/core/metrics.py`, including `chat_requests_total`, `agent_runs_total`, `document_uploads_total`, `document_processing_failures_total`, `image_analysis_total`, `llm_call_latency_seconds_count`, and `http_request_duration_seconds_count`.
