import glob
import json
import os
import shutil

import boto3
import fiona
import fiona.vfs
import pandas as pd
from botocore.exceptions import NoCredentialsError

if not hasattr(fiona, "path"):
    fiona.path = fiona.vfs

if not hasattr(pd, "Int64Index"):
    pd.Int64Index = pd.Index
if not hasattr(pd, "Float64Index"):
    pd.Float64Index = pd.Index

import geopandas as gpd


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "flood-results")


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


def merge_geojsons(input_dir, output_file):
    print(f"Reading GeoJSON files from: {input_dir}")

    files = sorted(glob.glob(os.path.join(input_dir, "depth_*.geojson")))
    if not files:
        print("No GeoJSON files found.")
        return False

    all_dfs = []
    print(f"Found {len(files)} files. Processing...")

    for file_path in files:
        try:
            filename = os.path.basename(file_path)
            raw_name = filename.replace("depth_", "").replace(".geojson", "")

            if len(raw_name) == 15 and "_" in raw_name:
                col_name = (
                    f"{raw_name[:4]}-{raw_name[4:6]}-{raw_name[6:8]}"
                    f"T{raw_name[9:11]}:{raw_name[11:13]}:{raw_name[13:]}"
                )
            else:
                col_name = raw_name

            with open(file_path, "r", encoding="utf-8") as geojson_file:
                data = json.load(geojson_file)

            if not data.get("features"):
                print(f"File {filename} has no features, skipping.")
                continue

            gdf = gpd.GeoDataFrame.from_features(data["features"])
            gdf.set_crs(epsg=4326, inplace=True)

            if "depth" in gdf.columns:
                gdf = gdf[["geometry", "depth"]].rename(columns={"depth": col_name})
            else:
                print(f"File {filename} is missing depth column, skipping.")
                continue

            gdf["geom_wkt"] = gdf["geometry"].apply(lambda geom: geom.wkt)
            df = pd.DataFrame(gdf.drop(columns="geometry"))
            all_dfs.append(df)

        except Exception as exc:
            print(f"Error reading file {file_path}: {exc}")

    if not all_dfs:
        return False

    print(f"Merging {len(all_dfs)} dataframes...")
    master_df = pd.concat(all_dfs)
    merged_df = master_df.groupby("geom_wkt").first().reset_index()
    merged_df = merged_df.fillna(0)

    print(f"Rebuilding GeoJSON ({len(merged_df)} polygons)...")
    geometry = gpd.GeoSeries.from_wkt(merged_df["geom_wkt"])
    final_gdf = gpd.GeoDataFrame(merged_df.drop(columns="geom_wkt"), geometry=geometry)
    final_gdf.set_crs(epsg=4326, inplace=True)

    final_gdf.to_file(output_file, driver="GeoJSON")
    print(f"Merged file created: {output_file}")
    return True


def upload_to_minio(file_path, object_name):
    s3 = get_s3_client()
    try:
        try:
            s3.head_bucket(Bucket=BUCKET_NAME)
        except Exception:
            print(f"Bucket {BUCKET_NAME} does not exist, creating...")
            s3.create_bucket(Bucket=BUCKET_NAME)

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


def run_merge_and_upload(geojson_dir, output_dir, tif_dir_to_clean=None):
    print("--- START MERGE & UPLOAD ---")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    current_time_str = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    merged_filename = f"flood_forecast_{current_time_str}.geojson"
    merged_path = os.path.join(output_dir, merged_filename)

    if merge_geojsons(geojson_dir, merged_path):
        if upload_to_minio(merged_path, merged_filename):
            if os.path.exists(merged_path):
                os.remove(merged_path)

            cleanup_files([geojson_dir])

            if tif_dir_to_clean:
                cleanup_files([tif_dir_to_clean])

            print(f"Merge & upload complete. MinIO file: {merged_filename}")
            return merged_filename

    print("Merge & upload failed.")
    return None
