# Flood Simulation & Forecasting System

This repository contains an Apache Airflow-based data engineering and simulation orchestration system. The system automates the triggering, execution, and downstream GIS processing of 2D hydrodynamic flood simulations (via the 3Di API). It combines simulation outputs, real-time weather forecasts (Tomorrow.io), and scraped telemetry to calculate localized flood depths, generate intersect-mapping GeoJSONs, and persist results to a MinIO (S3) bucket.

---

## 🛠️ Frameworks & Core Infrastructure

- **Apache Airflow (3.1.7):** The main orchestrator scheduling Python operators across DAGs.
- **Docker & Docker Compose:** Containerizes the application stack. Configured with a `CeleryExecutor`, using **PostgreSQL 16** for the metadata DB and **Redis 7.2** for the message broker.
- **Python 3.9:** Environment wrapped with physical and web dependencies.

### Key Python Libraries & Integrations
- **Geospatial & Vectorization:** `geopandas`, `rasterio` (1.4.4), `shapely`, `fiona`. Performs GIS bounding, merging, and transformations.
- **Hydrodynamic Context:** `threedidepth` – utilized to slice 3Di NetCDF array layers against raster DEM maps to calculate relative physics.
- **Web Scraping & OCR:** `selenium`, `webdriver-manager`, `pytesseract`, `opencv-python-headless`. Used dynamically to read graphic metric values off external visual dashboards.
- **Cloud/Object Storage:** `boto3` to communicate with the self-hosted or remote MinIO instance.

---

## 🏗️ Repository Architecture

* `dags/`: Stores the Airflow topology definitions.
  * `flood_forecast_dag.py`: Core forecast engine.
  * `flood_mapping_dag.py`: Mapping layer engine (intersects outputs with real-world map attributes like roads).
  * `initial_wl_dag.py`: Initiates standard system water levels and boundary preconditions.
  * `manholes_dag.py`: Tesseract pipeline handling rain and sewage water level sensor ingestion. 
* `scripts/`: Business logic explicitly called via Airflow PythonOperators. Contains logic for triggering the simulation, processing NetCDF matrices, and OCR processing.
* `data/`: Working directory (volume mounted into Airflow). 
  * Expects specific input artifacts: `dem.tif` (Digital Elevation Model), `gridadmin.h5` (3Di Grid context), and `toa-do-duong-hanoi.geojson` (Local Hanoi road coordinates).
  * Has sub-directories like `output_depths`, `output_geojsons`, and `output_final` used progressively down the pipeline.
* `docker-compose.yaml` / `Dockerfile`: Environment blueprint. 

---

## 🌊 Workflows In Detail

### 1. Flood Forecast Pipeline & Mapping Pipeline
These are the core modeling pipelines. They combine API orchestration and local spatial rendering.
1. **Trigger Simulation (`create_simulation.py`):** 
   - Reaches out to the **Tomorrow.io API** to fetch 1-hour interval precipitation forecasts using `LOCATION_LAT` & `LOCATION_LON`.
   - Uses the **3Di API** to spawn a hydrodynamic simulation template (Coldstart vs. Hotstart logic via saved states), injecting the rain volume array. 
2. **Download Results (`download_result.py`):** 
   - Awaits 3Di model completion, downloading the time-series raster array stored in `.nc` (NetCDF) format.
3. **Calculate Depth (`calculate_depth.py`):** 
   - Evaluates the downloaded `results_3di.nc` file against local `data/inputs/dem.tif` and `data/inputs/gridadmin.h5` to derive precise localized depth grids inside `data/output_depths`.
4. **Extract GeoJSON (`extract_geojson_full.py`):** 
   - Vectorizes depth rasters into spatial GeoJSON boundaries.
5. **Merge & Map (`mapping_geojson.py / merge_geojson.py`):**
   - Merges vector shapes and crosses the depth limits against infrastructural input (`toa-do-duong-hanoi.geojson`) to output a localized result: `road_flood_timeseries_generated.geojson` (mapping flooded roads).
6. **Upload & Clean (`upload_minio.py / merge_to_minio.py`):** 
   - Pushes the final mapped GeoJSON sequence up to a MinIO bucket bucket and drops local temp UUID folders.

### 2. Manhole & Rain Telemetry Pipeline (`manholes_dag.py`)
This pipeline retrieves external physical metric systems lacking a clean JSON API.
1. **Headless Scraping (`XuLyTramDo.py`):** 
   - Instructs `Selenium` to visit `thoatnuochanoi.vn/wt/` (Water Levels) and `thoatnuochanoi.vn/rain/` (Rain totals).
2. **OCR Parsing (`pytesseract`):** 
   - Locates metric widgets holding meter-values as embedded images.
   - Cleans and isolates digits dynamically from the image block (downscales, binary thresholds via `opencv-python`) and extracts standard metric text.
3. **Save & Sync:**
   - Bundles the reads with timestamps into `water_levels.csv` and `rain_levels.csv`, then uploads these logs directly to MinIO.

### 3. Initial Water Level Pipeline (`initial_wl_dag.py`)
Standardizes physical baseline conditions (tides, base reservoir volume) within the 3Di boundary settings. Runs prior to generalized rain forecasting.

---

## 🚀 Environment Requirements & How to Run

### 1. Prerequisites 
- **Docker** and **Docker Compose** installed.
- **Tesseract OCR** binary available (typically provided in the specific standard container image).

### 2. Required Input Context 
You must mount the following files in `/opt/airflow/data/inputs/` before execution:
- `dem.tif`: Digital Elevation Model.
- `gridadmin.h5`: 3Di admin map layout.
- `toa-do-duong-hanoi.geojson`: Road plotting data.

### 3. Environment Variables (Required in `.env`)
You should configure the following keys mapping the system APIs:
- **3Di:** `THREEDI_API_KEY`, `ORG_UUID`, `MODEL_ID`
- **Tomorrow.io:** `TOMORROW_API_KEY`, `LOCATION_LAT`, `LOCATION_LON`
- **MinIO Backup Storage:** `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET_NAME`

### 4. Running the Architecture 
1. Build and bring the containers online in detached mode:
   ```bash
   docker compose up -d
   ```
2. Navigate to the local Airflow Webserver UI at `http://localhost:8080`.
3. In the UI dashboard, utilize the toggle button to unpause (`flood_forecast_pipeline`, `manholes_waterlevel_rain_pipeline`, etc.) based on required monitoring frequencies.