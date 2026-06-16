# Local Valhalla for Hanoi

This folder runs a local Valhalla service for the flood-road test harness.

## What it does

1. Downloads the Geofabrik Vietnam OpenStreetMap PBF.
2. Uses `osmium extract` in Docker to cut a Hanoi-only PBF.
3. Mounts `custom_files/hanoi.osm.pbf` into the Valhalla Docker image.
4. Starts Valhalla on `http://localhost:8002`.

## Run

```bash
cd valhalla-flood-road-test/valhalla
chmod +x setup_hanoi_valhalla.sh
./setup_hanoi_valhalla.sh
```

Watch first graph build:

```bash
docker compose -f docker-compose.yml logs -f valhalla
```

Test from repo root:

```bash
python3 valhalla-flood-road-test/scripts/run_route_tests.py
python3 valhalla-flood-road-test/scripts/compare_routes.py
```

## Data scope

The Hanoi extract uses bbox:

```text
105.25,20.55,106.10,21.40
```

Format is `west,south,east,north`.
