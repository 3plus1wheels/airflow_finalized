import csv
import json
import requests
from datetime import datetime
import os
import boto3

# =========================
# CONFIG
# =========================
THREEDI_API_KEY = os.getenv("THREEDI_API_KEY")
MODEL_ID = int(os.getenv("THREEDI_MODEL_ID", "78136"))
BASE_URL = "https://api.3di.live/v3"

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")

MINIO_BUCKET = "initial-wl"
MINIO_PREFIX = "dummy-files"


# =========================
# COMMON
# =========================
def get_headers():
    api_key = THREEDI_API_KEY.strip()

    if api_key.lower().startswith("basic "):
        auth_value = api_key
    else:
        auth_value = f"Basic {api_key}"

    return {
        "Authorization": auth_value,
        "Content-Type": "application/json",
    }

# =========================
# MINIO
# =========================
def get_latest_csv():
    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )

    paginator = s3.get_paginator("list_objects_v2")

    csv_files = []
    for page in paginator.paginate(Bucket=MINIO_BUCKET, Prefix=MINIO_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".csv"):
                csv_files.append(obj)

    if not csv_files:
        raise ValueError("No CSV found in MinIO")

    latest = max(csv_files, key=lambda x: x["LastModified"])
    key = latest["Key"]

    local_path = f"/tmp/{os.path.basename(key)}"
    s3.download_file(MINIO_BUCKET, key, local_path)

    print(f"📥 CSV: {key}")
    return local_path


# =========================
# CSV → JSON
# =========================
def load_csv(csv_file):
    node_ids = []
    values = []

    with open(csv_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            node_ids.append(int(row["node_id"]))
            values.append(float(row["initial_waterlevel"]))

    return {
        "node_ids": node_ids,
        "values": values,
    }


# =========================
# 3DI API
# =========================
def create_resource():
    url = f"{BASE_URL}/threedimodels/{MODEL_ID}/initial_waterlevels/"
    res = requests.post(url, json={"dimension": "one_d"}, headers=get_headers())

    if res.status_code not in [200, 201]:
        raise Exception(f"Create resource failed: {res.text}")

    return res.json()["id"]


def get_upload_url(resource_id):
    url = f"{BASE_URL}/threedimodels/{MODEL_ID}/initial_waterlevels/{resource_id}/upload/"

    filename = f"initial_wl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    res = requests.post(url, json={"filename": filename}, headers=get_headers())

    if res.status_code not in [200, 201]:
        raise Exception(f"Get upload URL failed: {res.text}")

    data = res.json()
    return data.get("put_url") or data.get("upload_url") or data.get("url")


def upload(upload_url, data):
    print("⬆️ Uploading initial waterlevels JSON to 3Di storage...")

    file_content = json.dumps(data).encode("utf-8")

    res = requests.put(
        upload_url,
        data=file_content,
    )

    if res.status_code not in [200, 201, 204]:
        raise Exception(
            f"Upload failed: status={res.status_code}, response={res.text}"
        )

    print("✅ Uploaded initial waterlevels JSON")


# =========================
# MAIN (FOR AIRFLOW)
# =========================
def run_apply_initial_wl():
    csv_path = get_latest_csv()
    data = load_csv(csv_path)

    resource_id = create_resource()
    upload_url = get_upload_url(resource_id)

    upload(upload_url, data)

    print(f"✅ initial_wl_id = {resource_id}")

    return resource_id, None