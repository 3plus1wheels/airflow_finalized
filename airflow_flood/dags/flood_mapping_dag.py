from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from datetime import datetime, timedelta
import os
import sys


BASE_PATH = "/opt/airflow"
SCRIPTS_PATH = os.path.join(BASE_PATH, "scripts")
DATA_PATH = os.path.join(BASE_PATH, "data/mapping")

sys.path.append(SCRIPTS_PATH)

STATE_FILE = os.path.join(BASE_PATH, "state", "flood_system_state.json")
INPUT_DEM = os.path.join(DATA_PATH, "inputs", "dem.tif")
INPUT_GRID = os.path.join(DATA_PATH, "inputs", "gridadmin.h5")
RESULT_DIR = os.path.join(DATA_PATH, "results")
FIXTURE_RESULT_NC = os.path.join(RESULT_DIR, "results_3di.nc")
DEPTH_ROOT_DIR = os.path.join(DATA_PATH, "output_depths")
ROADS_GEOJSON_PATH = os.path.join(DATA_PATH, "inputs", "toa-do-duong-hanoi.geojson")
GEOJSON_ROOT_DIR = os.path.join(DATA_PATH, "output_geojsons")
FINAL_OUTPUT_ROOT_DIR = os.path.join(DATA_PATH, "output_final")
LOCAL_GEOJSON_ROOT_DIR = os.getenv(
    "LOCAL_GEOJSON_DIR", os.path.join(DATA_PATH, "output_road_geojson")
)
FLOOD_MAPPING_SCHEDULE = os.getenv("FLOOD_MAPPING_SCHEDULE")
if FLOOD_MAPPING_SCHEDULE and FLOOD_MAPPING_SCHEDULE.lower() in {"none", "null", "manual"}:
    FLOOD_MAPPING_SCHEDULE = None
USE_DOWNLOADED_RESULTS = os.getenv("FLOOD_USE_DOWNLOADED_RESULTS", "true").lower() in {
    "1",
    "true",
    "yes",
}
KEEP_LOCAL_GEOJSON = os.getenv("KEEP_LOCAL_GEOJSON", "false").lower() in {
    "1",
    "true",
    "yes",
}


def require_file(path, label):
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"Missing {label}: {path}")
    return path


def task_run_simulation(**kwargs):
    import create_simulation

    ti = kwargs["ti"]
    print("1. Trigger Simulation...")
    sim_id, _ = create_simulation.run_forecast_process(state_file_path=STATE_FILE)
    if not sim_id:
        raise ValueError("Failed to create simulation")
    ti.xcom_push(key="sim_id", value=sim_id)


def task_download_result(**kwargs):
    import download_result

    ti = kwargs["ti"]
    sim_id = ti.xcom_pull(task_ids="1_trigger_simulation", key="sim_id")
    print(f"2. Download results for Sim {sim_id}...")
    saved_path = download_result.run_download(sim_id, output_dir=RESULT_DIR)
    if not saved_path:
        raise ValueError("Download failed")
    ti.xcom_push(key="nc_path", value=saved_path)


def task_calculate_depth(**kwargs):
    import calculate_depth

    ti = kwargs["ti"]
    nc_path = ti.xcom_pull(task_ids="2_download_results", key="nc_path")
    if not USE_DOWNLOADED_RESULTS:
        print(f"Using fixture NetCDF for test mapping: {FIXTURE_RESULT_NC}")
        nc_path = FIXTURE_RESULT_NC

    print("3. Calculating Depth...")
    output_uuid_dir = calculate_depth.run_calculate_depth(
        grid_path=require_file(INPUT_GRID, "3Di grid admin file"),
        nc_path=require_file(nc_path, "downloaded 3Di result NetCDF"),
        dem_path=require_file(INPUT_DEM, "DEM raster"),
        output_dir=DEPTH_ROOT_DIR,
    )

    return output_uuid_dir


def task_extract_geojson_full(**kwargs):
    import mapping.extract_geojson_full

    ti = kwargs["ti"]
    input_depth_dir = ti.xcom_pull(task_ids="3_calculate_depth")

    print(f"4. Extracting GeoJSON from: {input_depth_dir}")
    current_uuid = os.path.basename(str(input_depth_dir))
    output_geojson_dir = os.path.join(GEOJSON_ROOT_DIR, current_uuid)

    mapping.extract_geojson_full.run_extract_geojson(
        input_dir=str(input_depth_dir), output_dir=str(output_geojson_dir)
    )

    return output_geojson_dir


def task_merge_geojson(**kwargs):
    import mapping.merge_geojson

    ti = kwargs["ti"]
    input_geojson_dir = ti.xcom_pull(task_ids="4_extract_geojson_full")

    run_ts = kwargs.get("ts_nodash") or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    ti.xcom_push(key="run_ts", value=run_ts)

    merged_path = mapping.merge_geojson.run_merge(
        geojson_dir=input_geojson_dir,
        output_dir=FINAL_OUTPUT_ROOT_DIR,
        run_ts=run_ts,
    )

    if not merged_path:
        raise ValueError("Merge failed.")

    return merged_path


def task_mapping_geojson(**kwargs):
    import mapping.mapping_geojson

    ti = kwargs["ti"]
    merged_flood_file = ti.xcom_pull(task_ids="5_merge_geojson")
    run_ts = ti.xcom_pull(task_ids="5_merge_geojson", key="run_ts")
    if not run_ts:
        run_ts = kwargs.get("ts_nodash") or datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    if not merged_flood_file or not os.path.exists(merged_flood_file):
        raise ValueError(f"Missing merged flood file: {merged_flood_file}")

    print("6. Mapping flood -> roads")
    print(f"   Input flood: {merged_flood_file}")

    mapping_output_dir = os.path.join(LOCAL_GEOJSON_ROOT_DIR, run_ts)
    mapping_output_file = os.path.join(
        mapping_output_dir,
        f"flood_road_{run_ts}.geojson",
    )

    print(f"   Output mapping: {mapping_output_file}")
    out_path = mapping.mapping_geojson.build_road_flood_timeseries_geojson(
        road_path=require_file(ROADS_GEOJSON_PATH, "roads GeoJSON"),
        flood_path=merged_flood_file,
        out_path=mapping_output_file,
    )

    print(f"Mapping done: {out_path}")
    return out_path


def task_upload_minio(**kwargs):
    import mapping.upload_minio

    ti = kwargs["ti"]
    mapping_file = ti.xcom_pull(task_ids="6_mapping_geojson")
    geojson_dir = ti.xcom_pull(task_ids="4_extract_geojson_full")

    run_ts = ti.xcom_pull(task_ids="5_merge_geojson", key="run_ts")
    if not run_ts:
        run_ts = kwargs.get("ts_nodash") or datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    result = mapping.upload_minio.run_upload(
        file_path=require_file(mapping_file, "mapped flood road GeoJSON"),
        geojson_dir_to_clean=geojson_dir,
        tif_dir_to_clean=None,
        delete_local_file_after_upload=not KEEP_LOCAL_GEOJSON,
        run_ts=run_ts,
    )

    if not result:
        raise ValueError("Upload MinIO failed")

    return result


default_args = {
    "owner": "flood_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    "flood_mapping_full",
    default_args=default_args,
    description="Pipeline 3Di -> MinIO (Direct Path Passing)",
    schedule=FLOOD_MAPPING_SCHEDULE,
    start_date=datetime(2026, 2, 5),
    catchup=False,
    is_paused_upon_creation=False,
    max_active_runs=1,
    tags=["3di", "flood"],
) as dag:
    t1 = PythonOperator(
        task_id="1_trigger_simulation", python_callable=task_run_simulation
    )
    t2 = PythonOperator(
        task_id="2_download_results", python_callable=task_download_result
    )
    t3 = PythonOperator(
        task_id="3_calculate_depth", python_callable=task_calculate_depth
    )
    t4 = PythonOperator(
        task_id="4_extract_geojson_full", python_callable=task_extract_geojson_full
    )
    t5 = PythonOperator(
        task_id="5_merge_geojson", python_callable=task_merge_geojson
    )
    t6 = PythonOperator(
        task_id="6_mapping_geojson", python_callable=task_mapping_geojson
    )
    t7 = PythonOperator(
        task_id="7_upload_minio", python_callable=task_upload_minio
    )

    t1 >> t2 >> t3 >> t4 >> t5 >> t6 >> t7
