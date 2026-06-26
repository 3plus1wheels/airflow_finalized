# Valhalla Flood Road GeoJSON Test Result

## Data

- File: `data/flood_road_20260522T103000.geojson`
- Geometry type: LineString
- Feature count: 1200
- Available time steps: `2026-05-22T18:00:00`, `2026-05-22T19:00:00`
- Depth unit: meters assumed
- Coordinate system: WGS84 lon/lat GeoJSON
- Bounding box: `105.71367244337159,20.978142146756962,105.78915739986421,21.023450802990816`

## What This Tests

This local harness converts flood-road LineStrings into Leaflet flood overlays and Valhalla `linear_cost_factors`.

Flow:

```text
Flood road GeoJSON -> selected time step -> polygon/road overlays -> depth factor -> Valhalla route -> compare route exposure
```

No GeoTIFF or point-to-road matching step runs here. Input file already contains road-aware LineStrings.

## Run

From this folder:

```bash
python3 scripts/inspect_flood_geojson.py
python3 scripts/extract_timesteps.py
python3 scripts/build_linear_cost_factors.py --time 2026-05-22T18:00:00
```

## Run Containerized Stack

## Large Data Files (Not In Git)

The repo does not include large Valhalla data files due to GitHub size limits. Generate them locally before running the stack:

```bash
cd valhalla-flood-road-test/valhalla
chmod +x setup_hanoi_valhalla.sh
./setup_hanoi_valhalla.sh
```

This script downloads the Vietnam PBF and builds Valhalla tiles under `valhalla/custom_files/`.

Build and start all services:

```bash
cd /Users/vova_nguyen/Documents/floodmap/valhalla-flood-road-test
docker compose up -d --build
```

Services:

- Frontend: `http://localhost:8080`
- Backend: `http://localhost:8010`
- Valhalla: `http://localhost:8002`

Smoke test:

```bash
curl http://localhost:8002/status
curl http://localhost:8010/health
curl -X POST http://localhost:8010/route/compare \
  -H "Content-Type: application/json" \
  -d '{"origin":{"lat":21.0214,"lon":105.7610},"destination":{"lat":21.0225,"lon":105.7650},"vehicle_type":"motorbike","flood_time_step":"2026-05-22T18:00:00"}'
```

Stop:

```bash
docker compose down
```

With local Valhalla running at `http://localhost:8002`:

```bash
python3 scripts/run_route_tests.py
python3 scripts/compare_routes.py
```

Run backend:

```bash
python3 backend/server.py
```

Open frontend:

```text
frontend/index.html
```

Backend listens on:

```text
http://127.0.0.1:8010
```

## API

- `GET /health`
- `GET /flood/timesteps`
- `GET /flood/polygons?time=2026-05-22T18:00:00`
- `GET /flood/roads?time=2026-05-22T18:00:00`
- `GET /flood/route/forecast?origin=21.0214,105.7610&destination=21.0225,105.7650&departure_time=2026-05-22T18:00:00&mode=nonempty&alternates=2`
- `POST /route/baseline`
- `POST /route/flood-aware`
- `POST /route/compare`

`/flood/route/forecast` returns bundled motorbike/car/truck ETAs, route alternatives, 8 water-level histogram bars for the visible 4h window, and best-departure labels scanned over the next 6h. Vehicle thresholds are 20/30/50 cm for motorbike/car/truck.

## Map Layers

Leaflet renders flood visualization separately from routing:

- Flood polygon layer: processed GeoJSON polygons styled by depth.
- Flooded road layer: road-aware LineStrings styled by depth/factor.
- Route layers: baseline, flood-aware, and shared route overlays.

The layer control can toggle polygons, roads, routes, shared segments, and markers independently. The current polygon endpoint derives display polygons from the processed flood-road GeoJSON; future flood polygon, raster, heatmap, or time-playback feeds should plug into the same `/flood/polygons` display contract.

## Factor Model

Motorbike flood-depth factor table:

| Water Depth | Factor | Meaning |
|---|---:|---|
| 0-3 cm | 1 | Normal |
| 3-5 cm | 2 | Small penalty |
| 5-10 cm | 8 | Avoid if possible |
| 10-15 cm | 25 | Strong avoid |
| 15-20 cm | 60 | Very strong avoid |
| 20 cm+ | 100 | Unsafe / hard-blocked with `exclude_locations` |

Features with `factor == 1` are skipped in Valhalla requests. Flooded roads below 20 cm use `linear_cost_factors` for soft avoidance. Flooded roads at or above 20 cm are also sampled into Valhalla `exclude_locations`, which hard-blocks the matched road edges during pathfinding.

## Test Case

- Origin: `21.0214, 105.7610`
- Destination: `21.0225, 105.7650`
- Vehicle type: motorbike
- Flood time step: `2026-05-22T18:00:00`
- Selected flooded road count: 26 route-nearby features in controlled test
- Valhalla version tested: 3.6.2
- Edge-walkable selected flooded roads: 21
- Rejected selected flooded roads: 5

## Result Table

| Test | Factor Source | Route Changed? | Flooded Road Exposure Reduced? | Distance | Duration | Max Depth Crossed | Result |
|---|---|---|---|---:|---:|---:|---|
| Baseline | none | N/A | No | 1.226 km | 2.40 min | 353 cm | OK |
| Flood-aware | flood road GeoJSON | Yes | Yes | 3.483 km | 5.54 min | 93 cm | PASS |
| Negative control | unrelated roads | No | N/A | 1.226 km | 2.40 min | 353 cm | OK |
| Hard-block control | `exclude_locations` for dangerous roads | Implemented | Implemented | TBD | TBD | TBD | Active |

## Conclusion

- Does this GeoJSON format work for `linear_cost_factors`? Yes, with Valhalla 3.6.2 and edge-walkable LineStrings.
- Does increasing factor reduce flooded-road usage? Yes. Route changed and affected flooded roads dropped from 21 to 2.
- Is this suitable for MVP? Yes, with a preflight step that filters or rematches features that fail Valhalla edge-walk.
- Do dangerous roads need hard-block logic? Implemented with `exclude_locations` for `depth >= 20 cm`.
- Is live panel demo working? Backend + frontend implemented; requires local backend, local Valhalla, and browser network access to Leaflet/OSM CDN.

Note: Valhalla docs describe `linear_cost_factors` as route request option. Valhalla 3.5.1 accepted unknown request fields but ignored them. Valhalla 3.6.2 applies them, but rejects any feature that fails edge-walk with `Failed to edge walk line feature`. The runner now probes features individually and keeps only edge-walkable flood LineStrings.
