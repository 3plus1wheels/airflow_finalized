import os
import shutil
import json

import boto3
import pandas as pd
from botocore.exceptions import ClientError, NoCredentialsError


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "flood-results-full")


def mask_value(value):
    if not value:
        return "<missing>"
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}***{value[-2:]}"


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
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        if code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
            raise RuntimeError(
                f"MinIO credentials cannot access bucket {BUCKET_NAME}: {code}"
            ) from exc

        print(f"Bucket {BUCKET_NAME} does not exist, creating it...")
        s3.create_bucket(Bucket=BUCKET_NAME)


def preflight_minio(s3, run_ts):
    print(
        "MinIO preflight: "
        f"endpoint={MINIO_ENDPOINT}, bucket={BUCKET_NAME}, "
        f"access_key={mask_value(MINIO_ACCESS_KEY)}"
    )
    ensure_bucket(s3)

    probe_key = f"{run_ts}/_airflow_minio_probe.txt"
    s3.put_object(Bucket=BUCKET_NAME, Key=probe_key, Body=b"ok")
    s3.head_object(Bucket=BUCKET_NAME, Key=probe_key)
    s3.delete_object(Bucket=BUCKET_NAME, Key=probe_key)
    print("MinIO preflight OK: credentials can write/read/delete.")


def upload_to_minio(file_path, object_name, run_ts):
    s3 = get_s3_client()

    try:
        preflight_minio(s3, run_ts)

        print(f"Uploading to MinIO: {BUCKET_NAME}/{object_name}")
        s3.upload_file(file_path, BUCKET_NAME, object_name)
        s3.head_object(Bucket=BUCKET_NAME, Key=object_name)
        print("Upload successful.")
        return True

    except NoCredentialsError:
        print("MinIO upload failed: credentials were not found.")
        return False
    except Exception as exc:
        print(f"MinIO upload failed: {exc}")
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
    file_path,
    geojson_dir_to_clean=None,
    tif_dir_to_clean=None,
    delete_local_file_after_upload=True,
    run_ts=None,
):
    """
    Verify the local GeoJSON first, then upload it to MinIO.

    Returns:
        dict | None: upload metadata on success, otherwise None.
    """
    print("--- START LOCAL GEOJSON CHECK + MINIO UPLOAD ---")

    if not file_path or not os.path.exists(file_path):
        print(f"Local GeoJSON does not exist: {file_path}")
        return None

    file_size = os.path.getsize(file_path)
    print(f"Local GeoJSON ready: {file_path} ({file_size} bytes)")

    if not run_ts:
        run_ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    try:
        with open(file_path, "r", encoding="utf-8") as geojson_file:
            feature_count = len(json.load(geojson_file).get("features", []))
    except Exception as exc:
        print(f"Local GeoJSON validation failed: {exc}")
        return None

    print(f"Local GeoJSON feature count: {feature_count}")

    object_name = f"{run_ts}/flood_road_{run_ts}.geojson"
    ok = upload_to_minio(file_path, object_name, run_ts)

    if not ok:
        print("Upload failed.")
        return None

    if delete_local_file_after_upload:
        try:
            os.remove(file_path)
            print(f"Deleted local file: {file_path}")
        except Exception as exc:
            print(f"Could not delete local file {file_path}: {exc}")
    else:
        print(f"Keeping local GeoJSON for inspection: {file_path}")

    if geojson_dir_to_clean:
        cleanup_files([geojson_dir_to_clean])

    if tif_dir_to_clean:
        cleanup_files([tif_dir_to_clean])

    print(f"UPLOAD COMPLETE. MinIO: {BUCKET_NAME}/{object_name}")
    return {
        "bucket": BUCKET_NAME,
        "object_name": object_name,
        "run_ts": run_ts,
        "local_path": file_path,
    }
