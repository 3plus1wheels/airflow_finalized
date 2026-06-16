from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import sys
import os

# ==============================================================================
# PATH
# ==============================================================================

BASE_PATH = "/opt/airflow"
SCRIPTS_PATH = os.path.join(BASE_PATH, "scripts")
DATA_PATH = os.path.join(BASE_PATH, "data")

sys.path.append(SCRIPTS_PATH)

from initial_wl import apply_initial_wl
from initial_wl import simulation_initial_wl
import download_result
import calculate_depth
from initial_wl import rename_folder_depth


# ==============================================================================
# CONFIG
# ==============================================================================

INPUT_DEM = os.path.join(DATA_PATH, "inputs", "dem.tif")
INPUT_GRID = os.path.join(DATA_PATH, "inputs", "gridadmin.h5")

RESULT_DIR = os.path.join(DATA_PATH, "results")
DEPTH_ROOT_DIR = os.path.join(DATA_PATH, "output_depths")


# ==============================================================================
# TASKS
# ==============================================================================

def task_apply_initial_wl(**kwargs):
    ti = kwargs["ti"]

    print("🚀 1. Applying Initial Water Level...")

    initial_wl_id, _ = apply_initial_wl.run_apply_initial_wl()

    if not initial_wl_id:
        raise ValueError("❌ Failed to apply initial water level")

    initial_wl_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    ti.xcom_push(key="initial_wl_id", value=initial_wl_id)
    ti.xcom_push(key="initial_wl_timestamp", value=initial_wl_timestamp)

    print(f"✅ Initial WL ID: {initial_wl_id}")
    print(f"🕒 Initial WL timestamp: {initial_wl_timestamp}")


def task_run_simulation(**kwargs):
    ti = kwargs["ti"]

    print("🚀 2. Running Simulation with Initial Water Level...")

    initial_wl_id = ti.xcom_pull(
        task_ids="1_apply_initial_wl",
        key="initial_wl_id",
    )

    if not initial_wl_id:
        raise ValueError("❌ initial_waterlevel ID not found in XCom")

    initial_waterlevel_resource_url = (
        f"{simulation_initial_wl.BASE_URL}/threedimodels/"
        f"{simulation_initial_wl.MODEL_ID}/initial_waterlevels/{initial_wl_id}/"
    )

    print(f"🌊 Initial WL resource URL: {initial_waterlevel_resource_url}")

    sim_id = simulation_initial_wl.run_simulation(
        initial_waterlevel_resource_url=initial_waterlevel_resource_url
    )

    if not sim_id:
        raise ValueError("❌ Failed to run simulation")

    ti.xcom_push(key="sim_id", value=sim_id)

    print(f"✅ Simulation completed: {sim_id}")


def task_download_result(**kwargs):
    ti = kwargs["ti"]

    sim_id = ti.xcom_pull(
        task_ids="2_run_simulation",
        key="sim_id",
    )

    if not sim_id:
        raise ValueError("❌ sim_id not found in XCom")

    print(f"⬇️ 3. Downloading results for Simulation {sim_id}...")

    saved_path = download_result.run_download(
        sim_id=sim_id,
        output_dir=RESULT_DIR,
    )

    if not saved_path:
        raise ValueError("❌ Download failed")

    ti.xcom_push(key="nc_path", value=saved_path)

    print(f"✅ Downloaded NetCDF: {saved_path}")


def task_calculate_depth(**kwargs):
    ti = kwargs["ti"]

    nc_path = ti.xcom_pull(
        task_ids="3_download_results",
        key="nc_path",
    )

    if not nc_path:
        raise ValueError("❌ nc_path not found in XCom")

    print("⚙️ 4. Calculating Depth...")
    print(f"📄 NetCDF: {nc_path}")
    print(f"📄 Grid: {INPUT_GRID}")
    print(f"📄 DEM: {INPUT_DEM}")

    output_uuid_dir = calculate_depth.run_calculate_depth(
        grid_path=INPUT_GRID,
        nc_path=nc_path,
        dem_path=INPUT_DEM,
        output_dir=DEPTH_ROOT_DIR,
    )

    if not output_uuid_dir:
        raise ValueError("❌ Depth calculation failed")

    print(f"✅ Depth output directory: {output_uuid_dir}")

    return output_uuid_dir


def task_rename_depth_folder(**kwargs):
    ti = kwargs["ti"]

    output_uuid_dir = ti.xcom_pull(
        task_ids="4_calculate_depth",
    )

    initial_wl_timestamp = ti.xcom_pull(
        task_ids="1_apply_initial_wl",
        key="initial_wl_timestamp",
    )

    if not output_uuid_dir:
        raise ValueError("❌ output_uuid_dir not found in XCom")

    if not initial_wl_timestamp:
        raise ValueError("❌ initial_wl_timestamp not found in XCom")

    print("📁 5. Renaming depth output folder...")
    print(f"📂 Depth output dir: {output_uuid_dir}")
    print(f"🕒 Initial WL timestamp: {initial_wl_timestamp}")

    renamed_dir = rename_folder_depth.run_rename_depth(
        output_uuid_dir=output_uuid_dir,
        initial_wl_timestamp=initial_wl_timestamp,
    )

    if not renamed_dir:
        raise ValueError("❌ Failed to rename depth folder")

    ti.xcom_push(key="renamed_depth_dir", value=renamed_dir)

    print("✅ Depth folder renamed successfully.")
    print(f"📂 Renamed folder: {renamed_dir}")


# ==============================================================================
# DAG
# ==============================================================================

default_args = {
    "owner": "flood_team",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    dag_id="flood_initial_wl_pipeline",
    default_args=default_args,
    description="3Di pipeline: initial WL -> simulation -> download -> calculate depth -> rename folder",
    schedule="*/30 * * * *",
    start_date=datetime(2026, 2, 5),
    catchup=False,
    max_active_runs=1,
    tags=["3di", "flood", "initial_wl", "depth"],
) as dag:

    t1 = PythonOperator(
        task_id="1_apply_initial_wl",
        python_callable=task_apply_initial_wl,
    )

    t2 = PythonOperator(
        task_id="2_run_simulation",
        python_callable=task_run_simulation,
    )

    t3 = PythonOperator(
        task_id="3_download_results",
        python_callable=task_download_result,
    )

    t4 = PythonOperator(
        task_id="4_calculate_depth",
        python_callable=task_calculate_depth,
    )

    t5 = PythonOperator(
        task_id="5_rename_depth_folder",
        python_callable=task_rename_depth_folder,
    )

    t1 >> t2 >> t3 >> t4 >> t5