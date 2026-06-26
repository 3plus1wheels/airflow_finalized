import os
import shutil

import boto3
import pandas as pd
from botocore.exceptions import ClientError, NoCredentialsError


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "flood-results-full")


def require_minio_env():
    values = {
        "MINIO_ENDPOINT": MINIO_ENDPOINT,
        "MINIO_ACCESS_KEY": MINIO_ACCESS_KEY,
        "MINIO_SECRET_KEY": MINIO_SECRET_KEY,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            f"Missing required MinIO environment variables: {', '.join(missing)}"
        )


def get_s3_client():
    require_minio_env()
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
    )


def ensure_bucket(s3):
    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
    except ClientError:
        print(f"Bucket {BUCKET_NAME} does not exist, creating...")
        s3.create_bucket(Bucket=BUCKET_NAME)


def upload_to_minio(file_path: str, object_name: str) -> bool:
    s3 = get_s3_client()

    try:
        ensure_bucket(s3)
        print(f"Uploading to MinIO: {BUCKET_NAME}/{object_name}")
        s3.upload_file(file_path, BUCKET_NAME, object_name)
        print("Upload successful.")
        return True

    except NoCredentialsError:
        print("MinIO credentials not found.")
        return False
    except Exception as exc:
        print(f"Upload error: {exc}")
        return False


def cleanup_files(dirs_to_clean):
    print("Cleaning temporary files...")
    for directory in dirs_to_clean:
        if directory and os.path.exists(directory):
            try:
                shutil.rmtree(directory)
                print(f"   -> Deleted: {directory}")
            except Exception as exc:
                print(f"   -> Could not delete {directory}: {exc}")


def run_upload(
    file_path: str,
    geojson_dir_to_clean: str = None,
    tif_dir_to_clean: str = None,
    delete_local_file_after_upload: bool = True,
    run_ts: str = None,
):
    print("--- START UPLOAD ---")

    if not file_path or not os.path.exists(file_path):
        print(f"File does not exist: {file_path}")
        return None

    if not run_ts:
        run_ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    object_name = f"{run_ts}/flood_road_{run_ts}.geojson"
    ok = upload_to_minio(file_path, object_name)

    if ok:
        if delete_local_file_after_upload:
            try:
                os.remove(file_path)
                print(f"Deleted local file: {file_path}")
            except Exception as exc:
                print(f"Could not delete local file {file_path}: {exc}")

        if geojson_dir_to_clean:
            cleanup_files([geojson_dir_to_clean])

        if tif_dir_to_clean:
            cleanup_files([tif_dir_to_clean])

        print(f"Upload complete. MinIO: {BUCKET_NAME}/{object_name}")
        return {"bucket": BUCKET_NAME, "object_name": object_name, "run_ts": run_ts}

    print("Upload failed.")
    return None
