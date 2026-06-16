from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import os
import sys

# =========================
# PATH
# =========================
BASE_PATH = "/opt/airflow"
SCRIPTS_PATH = os.path.join(BASE_PATH, "scripts")
sys.path.append(SCRIPTS_PATH)

from initial_wl.generate_initial_wl import generate_initial_wl, upload_to_minio

# =========================
# DAG CONFIG
# =========================
default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    dag_id="initial_wl_dummy_pipeline",
    default_args=default_args,
    schedule="*/10 * * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["initial_wl", "minio"],
) as dag:

    # ===== task 1: generate csv =====
    task_generate = PythonOperator(
        task_id="generate_csv",
        python_callable=generate_initial_wl,
    )

    # ===== task 2: upload =====
    task_upload = PythonOperator(
        task_id="upload_minio",
        python_callable=upload_to_minio,
        op_kwargs={
            "file_path": "{{ ti.xcom_pull(task_ids='generate_csv') }}"
        },
    )

    # ===== workflow =====
    task_generate >> task_upload