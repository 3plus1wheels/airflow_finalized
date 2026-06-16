import os
import glob
import shutil
import boto3
import json
import pandas as pd
import fiona
import fiona.vfs

# Monkey patch for fiona 1.9+ compatibility with older geopandas
if not hasattr(fiona, "path"):
    fiona.path = fiona.vfs

# Monkey patch for pandas 2.0+ compatibility
if not hasattr(pd, "Int64Index"):
    pd.Int64Index = pd.Index
if not hasattr(pd, "Float64Index"):
    pd.Float64Index = pd.Index

import geopandas as gpd
from botocore.exceptions import NoCredentialsError

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "flood-results-full")


def merge_geojsons(input_dir: str, output_file: str) -> bool:
    """
    Hàm gộp các file GeoJSON lẻ thành 1 file duy nhất.
    Cột 'depth' sẽ được đổi tên thành thời gian tương ứng.
    """
    print(f"🔄 Đang đọc file từ: {input_dir}")

    if not input_dir:
        print("❌ Input directory is None.")
        return False

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
                col_name = (
                    f"{raw_name[:4]}-{raw_name[4:6]}-{raw_name[6:8]}"
                    f"T{raw_name[9:11]}:{raw_name[11:13]}:{raw_name[13:]}"
                )
            else:
                col_name = raw_name

            # Workaround for "module 'fiona' has no attribute 'path'"
            with open(f, "r", encoding="utf-8") as geojson_file:
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
        print("❌ Không có dataframe hợp lệ để gộp.")
        return False

    print(f"🧩 Đang gộp {len(all_dfs)} dataframes...")
    master_df = pd.concat(all_dfs, ignore_index=True)
    merged_df = master_df.groupby("geom_wkt").first().reset_index()
    merged_df = merged_df.fillna(0)

    print(f"🗺️ Đang tái tạo GeoJSON ({len(merged_df)} polygons)...")
    geometry = gpd.GeoSeries.from_wkt(merged_df["geom_wkt"])
    final_gdf = gpd.GeoDataFrame(merged_df.drop(columns="geom_wkt"), geometry=geometry)
    final_gdf.set_crs(epsg=4326, inplace=True)

    # đảm bảo thư mục output tồn tại
    out_dir = os.path.dirname(output_file)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    final_gdf.to_file(output_file, driver="GeoJSON")
    print(f"✅ Đã tạo file gộp: {output_file}")
    return True


def get_s3_client():
    values = {
        "MINIO_ENDPOINT": MINIO_ENDPOINT,
        "MINIO_ACCESS_KEY": MINIO_ACCESS_KEY,
        "MINIO_SECRET_KEY": MINIO_SECRET_KEY,
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required MinIO environment variables: {', '.join(missing)}")

    # Giống script 2
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
    )


def ensure_bucket(s3) -> None:
    # Giống logic script 2 (head_bucket -> create_bucket)
    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
    except Exception:
        print(f"Bucket {BUCKET_NAME} chưa tồn tại, đang tạo...")
        s3.create_bucket(Bucket=BUCKET_NAME)


def upload_to_minio(file_path: str, object_name: str) -> bool:
    # Giống script 2
    s3 = get_s3_client()
    try:
        ensure_bucket(s3)

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


def run_merge(
    geojson_dir: str,
    output_dir: str,
    tif_dir_to_clean: str = None,
    run_ts: str = None,  
):
    """
    Returns:
        str: object_name đã upload lên MinIO (hoặc None nếu lỗi).
    """
    print("--- 🚀 START MERGE ---")

    if not geojson_dir:
        print("❌ Merge thất bại: geojson_dir is None.")
        return None

    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # timestamp prefix 
    if not run_ts:
        run_ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    object_name = f"{run_ts}/flood_{run_ts}.geojson"

    merged_path = os.path.join(output_dir, object_name)
    os.makedirs(os.path.dirname(merged_path), exist_ok=True)

    if merge_geojsons(geojson_dir, merged_path):
        if upload_to_minio(merged_path, object_name):

            cleanup_files([geojson_dir])
            if tif_dir_to_clean:
                cleanup_files([tif_dir_to_clean])

            print(f"🎉 QUY TRÌNH HOÀN TẤT! File trên MinIO: {object_name}")
            return merged_path
            
    print("❌ Merge thất bại.")
    return None
