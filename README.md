# Integrated Flood Stack

This repository now has one top-level Docker Compose app that connects:

- `airflow_flood`: Airflow flood processing pipeline.
- `minio_custom`: MinIO plus Django/React storage UI.
- `floodmap/valhalla-flood-road-test`: Valhalla-backed flood-aware routing map.

## Run

Create a local env file, then start the stack:

```bash
cp .env.example .env
docker compose up --build
```

Local URLs:

- Airflow: http://localhost:8080
- Floodmap: http://localhost:8081
- MinIO custom UI: http://localhost:5173
- MinIO API: http://localhost:9000
- MinIO console: http://localhost:9001

## Data Flow

On startup, the `minio-init` service creates the configured bucket if it does not already exist. The default bucket is:

```text
flood-results-full
```

Airflow uploads generated road-flood GeoJSON objects to the shared MinIO service:

```text
s3://flood-results-full/<run_ts>/flood_road_<run_ts>.geojson
```

The floodmap backend lists that bucket, loads the newest timestamped `flood_road_*.geojson`, and uses it for map overlays and flood-aware routing. If no Airflow object exists yet, it falls back to the bundled sample GeoJSON.

## Smoke Checks

```bash
docker compose --env-file .env.example config
docker compose up --build
curl http://localhost:8010/health
curl http://localhost:8010/flood/timesteps
```

The `/health` response includes `flood_geojson_source`, which should be an `s3://...` path after Airflow has uploaded a result.
