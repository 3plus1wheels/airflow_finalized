from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import os
import sys

BASE_PATH = "/opt/airflow"
SCRIPTS_PATH = os.path.join(BASE_PATH, "scripts")
sys.path.append(SCRIPTS_PATH)

from manholes.XuLyTramDo import (
    scrape_all_data,
    save_all_csv,
    upload_all_to_minio,
)

default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    dag_id="manholes_waterlevel_rain_pipeline",
    default_args=default_args,
    schedule="0 */2 * * *",
    start_date=datetime(2026, 5, 5),
    catchup=False,
    tags=["water", "rain", "minio"],
) as dag:

    task_scrape = PythonOperator(
        task_id="scrape_waterlevel_and_rain",
        python_callable=scrape_all_data,
    )

    task_save = PythonOperator(
        task_id="save_csv_files",
        python_callable=save_all_csv,
        op_kwargs={
            "data": task_scrape.output
        },
    )

    task_upload = PythonOperator(
        task_id="upload_to_minio",
        python_callable=upload_all_to_minio,
        op_kwargs={
            "files": task_save.output
        },
    )

    task_scrape >> task_save >> task_upload