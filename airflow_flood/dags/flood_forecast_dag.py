from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys
import os


BASE_PATH = "/opt/airflow"
SCRIPTS_PATH = os.path.join(BASE_PATH, "scripts")
DATA_PATH = os.path.join(BASE_PATH, "data")

sys.path.append(SCRIPTS_PATH)

try:
    import create_simulation
    import download_result
    import calculate_depth
    import extract_geojson
    import merge_to_minio
except ImportError as e:
    print(f"❌ Lỗi Import: {e}")


STATE_FILE = os.path.join(BASE_PATH, "state", "flood_system_state.json")
INPUT_DEM = os.path.join(DATA_PATH, "inputs", "dem.tif")
INPUT_GRID = os.path.join(DATA_PATH, "inputs", "gridadmin.h5")
RESULT_DIR = os.path.join(DATA_PATH, "results")
DEPTH_ROOT_DIR = os.path.join(DATA_PATH, "output_depths")
GEOJSON_ROOT_DIR = os.path.join(DATA_PATH, "output_geojsons")
FINAL_OUTPUT_ROOT_DIR = os.path.join(DATA_PATH, "output_final")


def task_run_simulation(**kwargs):
    ti = kwargs["ti"]
    print("🚀 1. Trigger Simulation...")
    sim_id, _ = create_simulation.run_forecast_process(state_file_path=STATE_FILE)
    if not sim_id:
        raise ValueError("❌ Failed to create simulation")
    ti.xcom_push(key="sim_id", value=sim_id)


def task_download_result(**kwargs):
    ti = kwargs["ti"]
    sim_id = ti.xcom_pull(task_ids="1_trigger_simulation", key="sim_id")
    print(f"⬇️ 2. Download results for Sim {sim_id}...")
    saved_path = download_result.run_download(sim_id, output_dir=RESULT_DIR)
    if not saved_path:
        raise ValueError("❌ Download failed")
    ti.xcom_push(key="nc_path", value=saved_path)


def task_calculate_depth(**kwargs):
    """
    Task này sẽ trả về đường dẫn thư mục UUID vừa tạo.
    Ví dụ return: /opt/airflow/data/output_depths/a1b2c3d4
    """
    ti = kwargs["ti"]
    nc_path = ti.xcom_pull(task_ids="2_download_results", key="nc_path")

    print("⚙️ 3. Calculating Depth...")

    output_uuid_dir = calculate_depth.run_calculate_depth(
        grid_path=INPUT_GRID,
        nc_path=nc_path,
        dem_path=INPUT_DEM,
        output_dir=DEPTH_ROOT_DIR,
    )

    return output_uuid_dir


def task_extract_geojson(**kwargs):
    """
    Nhận đường dẫn Depth từ Task 3 -> Tạo đường dẫn GeoJSON tương ứng -> Chạy convert
    """
    ti = kwargs["ti"]

    input_depth_dir = ti.xcom_pull(task_ids="3_calculate_depth")

    print(f"🗺️ 4. Extracting GeoJSON from: {input_depth_dir}")

    current_uuid = os.path.basename(input_depth_dir)
    output_geojson_dir = os.path.join(GEOJSON_ROOT_DIR, current_uuid)

    extract_geojson.run_extract_geojson(
        input_dir=input_depth_dir, output_dir=output_geojson_dir
    )

    return output_geojson_dir


def task_merge_upload(**kwargs):
    """
    Nhận đường dẫn GeoJSON từ Task 4 -> Merge -> Upload
    """
    ti = kwargs["ti"]

    input_geojson_dir = ti.xcom_pull(task_ids="4_extract_geojson")

    input_depth_dir = ti.xcom_pull(task_ids="3_calculate_depth")

    print(f"☁️ 5. Merging & Uploading from: {input_geojson_dir}")

    final_file = merge_to_minio.run_merge_and_upload(
        geojson_dir=input_geojson_dir,
        output_dir=FINAL_OUTPUT_ROOT_DIR,
        tif_dir_to_clean=input_depth_dir,
    )

    if not final_file:
        raise ValueError("❌ Merge/Upload failed.")

    print(f"🎉 DONE! File: {final_file}")


default_args = {
    "owner": "flood_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    "flood_forecast_pipeline",
    default_args=default_args,
    description="Pipeline 3Di -> MinIO (Direct Path Passing)",
    schedule="*/30 * * * *",
    start_date=datetime(2026, 2, 5),
    catchup=False,
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
        task_id="4_extract_geojson", python_callable=task_extract_geojson
    )
    t5 = PythonOperator(
        task_id="5_merge_upload_cleanup", python_callable=task_merge_upload
    )

    t1 >> t2 >> t3 >> t4 >> t5
