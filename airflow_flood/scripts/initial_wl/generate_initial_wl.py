import csv
from datetime import datetime
import random
import boto3
import os

# =========================
# CONFIG
# =========================
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")

MINIO_BUCKET = "initial-wl"
MINIO_PREFIX = "dummy-files"

node_ids = list(range(33471, 33493))  # 22 nodes


# =========================
# GENERATE CSV
# =========================
def generate_initial_wl():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"/tmp/initial_wl_{timestamp}.csv"

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["node_id", "initial_waterlevel"])

        for node_id in node_ids:
            waterlevel = round(random.uniform(0, 2), 2)
            writer.writerow([node_id, waterlevel])

    print(f"✅ Generated CSV: {filename}")

    return filename


# =========================
# UPLOAD MINIO
# =========================
def upload_to_minio(file_path: str):
    print("📡 Uploading to MinIO...")

    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
    )

    # create bucket if needed
    try:
        s3.head_bucket(Bucket=MINIO_BUCKET)
    except Exception:
        s3.create_bucket(Bucket=MINIO_BUCKET)

    filename = os.path.basename(file_path)
    object_name = f"{MINIO_PREFIX}/{filename}"

    s3.upload_file(
        file_path,
        MINIO_BUCKET,
        object_name,
        ExtraArgs={"ContentType": "text/csv"},
    )

    print(f"⬆️ Uploaded: s3://{MINIO_BUCKET}/{object_name}")

    return f"s3://{MINIO_BUCKET}/{object_name}"