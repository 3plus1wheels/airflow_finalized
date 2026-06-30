# Integrated Flood Stack

This repository now has one top-level Docker Compose app that connects:

- `airflow_flood`: Airflow flood processing pipeline.
- `minio_custom`: MinIO plus Django/React storage UI.
- `floodmap/valhalla-flood-road-test`: Valhalla-backed flood-aware routing map.

## Run the Entire Stack

These steps start the integrated Docker Compose stack:

- Airflow pipeline
- MinIO object storage
- Django/React MinIO custom UI
- Valhalla routing service
- Floodmap backend and frontend
- PostgreSQL and Redis support services

### 1. Install prerequisites

Install Docker Desktop or Docker Engine with Docker Compose v2.

Check that Docker is available:

```bash
docker --version
docker compose version
```

### 2. Clone the repository

```bash
git clone <repo-url>
cd airflow_finalized
```

If the repository is already on the server, go to the repository root where this `README.md` and `compose.yml` file are located.

### 3. Create the environment file

```bash
cp .env.example .env
```

Edit `.env` before running the full live pipeline.

At minimum, replace the placeholder values for:

```text
MINIO_ROOT_PASSWORD
DJANGO_SECRET_KEY
POSTGRES_PASSWORD
THREEDI_API_KEY
TOMORROW_API_KEY
ORG_UUID
MODEL_ID
THREEDI_MODEL_ID
```

For a local UI-only smoke test, the placeholders can be left in place, but real Airflow flood jobs need valid external API credentials.

### 4. Validate the Compose configuration

```bash
docker compose --env-file .env config
```

If this prints the resolved configuration without errors, the Compose file and required environment variables are valid.

### 5. Build and start all services

```bash
docker compose up --build
```

Leave this terminal open to watch logs.

To run in the background instead:

```bash
docker compose up -d --build
```

The first startup can take several minutes because Docker has to build local images, initialize PostgreSQL, start Airflow, and start Valhalla.

### 6. Open the local services

After startup, open:

- Airflow: http://localhost:8080
- Floodmap: http://localhost:8081
- MinIO custom UI: http://localhost:5173
- MinIO API: http://localhost:9000
- MinIO console: http://localhost:9001
- Floodmap backend health: http://localhost:8010/health

Default Airflow login comes from `.env`:

```text
Username: _AIRFLOW_WWW_USER_USERNAME
Password: _AIRFLOW_WWW_USER_PASSWORD
```

Default MinIO console login comes from `.env`:

```text
Username: MINIO_ROOT_USER
Password: MINIO_ROOT_PASSWORD
```

### 7. Create the first MinIO custom UI user

After the stack is running, create a Django superuser for the MinIO custom UI:

```bash
docker compose exec storage-backend python manage.py createsuperuser
```

Then log in at:

```text
http://localhost:5173
```

Use the Admin tab to create normal users, groups, and bucket or prefix visibility grants.

### 8. Check that the floodmap backend is healthy

```bash
curl http://localhost:8010/health
curl http://localhost:8010/flood/timesteps
```

The `/health` response includes `flood_geojson_source`.

- Before Airflow uploads a result, this can point to the bundled sample GeoJSON.
- After Airflow uploads a result, it should point to an `s3://...` MinIO object.

### 9. Trigger or inspect Airflow

Open Airflow:

```text
http://localhost:8080
```

The top-level stack includes a startup trigger service for the flood mapping DAG. You can also inspect DAG status, logs, and task runs from the Airflow UI.

### 10. Stop the stack

Stop services but keep Docker volumes and stored data:

```bash
docker compose down
```

Stop services and remove volumes, including PostgreSQL and MinIO data:

```bash
docker compose down -v
```

Use `down -v` only when you intentionally want to delete local generated data.

## VPS Deployment Notes

For VPS deployment:

- Replace all placeholder secrets and API keys in `.env`.
- Keep PostgreSQL and MinIO private unless there is a specific reason to expose them.
- Put a TLS reverse proxy, Cloudflare Tunnel, or similar public entrypoint in front of user-facing services.
- Update `DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ALLOWED_ORIGINS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `MINIO_PUBLIC_ENDPOINT`, and frontend/API URLs for the VPS domain.
- Make sure the VPS has enough CPU, RAM, and disk for Docker images, databases, MinIO objects, logs, and generated flood outputs.

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
