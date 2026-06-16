import os
import glob
import shutil
import boto3
import json
import pandas as pd
import fiona
import fiona.vfs

# Monkey patch for fiona 1.9+ compatibility with older geopandas
if not hasattr(fiona, 'path'):
    fiona.path = fiona.vfs

# Monkey patch for pandas 2.0+ compatibility
if not hasattr(pd, 'Int64Index'):
    pd.Int64Index = pd.Index
if not hasattr(pd, 'Float64Index'):
    pd.Float64Index = pd.Index

import geopandas as gpd
from botocore.exceptions import NoCredentialsError


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "flood-results")


def get_s3_client():
    values = {
        "MINIO_ENDPOINT": MINIO_ENDPOINT,
        "MINIO_ACCESS_KEY": MINIO_ACCESS_KEY,
        "MINIO_SECRET_KEY": MINIO_SECRET_KEY,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required MinIO environment variables: {', '.join(missing)}")

    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
    )


def merge_geojsons(input_dir, output_file):
    """
    Hàm gộp các file GeoJSON lẻ thành 1 file duy nhất.
    Cột 'depth' sẽ được đổi tên thành thời gian tương ứng.
    """
    print(f"🔄 Đang đọc file từ: {input_dir}")

    files = sorted(glob.glob(os.path.join(input_dir, "depth_*.geojson")))

    if not files:
        print("❌ Không tìm thấy file GeoJSON nào.")
        return False

    all_dfs = []
    print(f"⚡ Tìm thấy {len(files)} file. Đang xử lý...")

    for f in files:
        try:
            filename = os.path.basename(f)

            raw_name = filename.replace("depth_", "").replace(".geojson", "")

            if len(raw_name) == 15 and "_" in raw_name:
                col_name = f"{raw_name[:4]}-{raw_name[4:6]}-{raw_name[6:8]}T{raw_name[9:11]}:{raw_name[11:13]}:{raw_name[13:]}"
            else:
                col_name = raw_name

            # Workaround for "module 'fiona' has no attribute 'path'"
            with open(f, 'r', encoding='utf-8') as geojson_file:
                data = json.load(geojson_file)

            if not data.get("features"):
                print(f"⚠️ File {filename} không có features, bỏ qua.")
                continue

            gdf = gpd.GeoDataFrame.from_features(data["features"])
            # Các file geojson được tạo ra ở bước trước đã ở EPSG:4326
            gdf.set_crs(epsg=4326, inplace=True)

            if "depth" in gdf.columns:
                gdf = gdf[["geometry", "depth"]].rename(columns={"depth": col_name})
            else:
                print(f"⚠️ File {filename} thiếu cột 'depth', bỏ qua.")
                continue

            gdf["geom_wkt"] = gdf["geometry"].apply(lambda x: x.wkt)

            df = pd.DataFrame(gdf.drop(columns="geometry"))
            all_dfs.append(df)

        except Exception as e:
            print(f"⚠️ Lỗi đọc file {f}: {e}")

    if not all_dfs:
        return False

    print(f"🧩 Đang gộp {len(all_dfs)} dataframes...")
    master_df = pd.concat(all_dfs)

    merged_df = master_df.groupby("geom_wkt").first().reset_index()

    merged_df = merged_df.fillna(0)

    print(f"🗺️ Đang tái tạo GeoJSON ({len(merged_df)} polygons)...")

    geometry = gpd.GeoSeries.from_wkt(merged_df["geom_wkt"])
    final_gdf = gpd.GeoDataFrame(merged_df.drop(columns="geom_wkt"), geometry=geometry)

    final_gdf.set_crs(epsg=4326, inplace=True)

    final_gdf.to_file(output_file, driver="GeoJSON")
    print(f"✅ Đã tạo file gộp: {output_file}")
    return True


def upload_to_minio(file_path, object_name):
    s3 = get_s3_client()
    try:

        try:
            s3.head_bucket(Bucket=BUCKET_NAME)
        except:
            print(f"Bucket {BUCKET_NAME} chưa tồn tại, đang tạo...")
            s3.create_bucket(Bucket=BUCKET_NAME)

        print(f"☁️ Đang Upload lên MinIO: {BUCKET_NAME}/{object_name}")
        s3.upload_file(file_path, BUCKET_NAME, object_name)
        print("✅ Upload thành công!")
        return True
    except NoCredentialsError:
        print("❌ Lỗi: Không tìm thấy Credentials MinIO.")
        return False
    except Exception as e:
        print(f"❌ Lỗi Upload: {e}")
        return False


def cleanup_files(dirs_to_clean):
    """Xóa các thư mục tạm sau khi xử lý xong"""
    print("🧹 Dọn dẹp file tạm...")
    for d in dirs_to_clean:
        if d and os.path.exists(d):
            try:
                shutil.rmtree(d)
                print(f"   -> Đã xóa: {d}")
            except Exception as e:
                print(f"   -> Lỗi xóa {d}: {e}")


def run_merge_and_upload(geojson_dir, output_dir, tif_dir_to_clean=None):
    """
    Hàm chính được gọi bởi Airflow.

    Args:
        geojson_dir (str): Đường dẫn chứa các file geojson lẻ (Input).
        output_dir (str): Đường dẫn lưu file gộp tạm thời (Output Temp).
        tif_dir_to_clean (str): Đường dẫn folder TIF để xóa dọn dẹp (Optional).

    Returns:
        str: Tên file đã upload lên MinIO (hoặc None nếu lỗi).
    """
    print("--- 🚀 START MERGE & UPLOAD ---")

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

            print(f"🎉 QUY TRÌNH HOÀN TẤT! File trên MinIO: {merged_filename}")
            return merged_filename

    print("❌ Quy trình thất bại.")
    return None
