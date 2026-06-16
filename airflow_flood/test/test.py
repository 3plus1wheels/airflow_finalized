"""
File: test_local_pipeline.py
Mục đích: Chạy thử nghiệm toàn bộ pipeline Flood Mapping trên môi trường local (không cần Airflow).
Cách dùng: python test_local_pipeline.py
"""

import os
import sys
import time

# ==========================================
# 1. CẤU HÌNH ĐƯỜNG DẪN (LOCAL PATHS)
# ==========================================
# Đường dẫn gốc dự án trên máy của bạn
BASE_PATH = "/Users/tungdv/Work/TSM/airflow_tsm"
SCRIPTS_PATH = os.path.join(BASE_PATH, "scripts")

# Thêm scripts vào sys.path để import được các module
if SCRIPTS_PATH not in sys.path:
    sys.path.append(SCRIPTS_PATH)

# Cấu hình thư mục dữ liệu (tương tự DAG nhưng trỏ về local)
DATA_PATH = os.path.join(BASE_PATH, "data/mapping")
STATE_FILE = os.path.join(BASE_PATH, "state", "flood_system_state.json")

# Inputs
INPUT_DEM = os.path.join(DATA_PATH, "inputs", "dem.tif")
INPUT_GRID = os.path.join(DATA_PATH, "inputs", "gridadmin.h5")
ROADS_GEOJSON_PATH = os.path.join(DATA_PATH, "inputs", "toa-do-duong-hanoi.geojson")

# Outputs
RESULT_DIR = os.path.join(DATA_PATH, "results")
DEPTH_ROOT_DIR = os.path.join(DATA_PATH, "output_depths")
GEOJSON_ROOT_DIR = os.path.join(DATA_PATH, "output_geojsons")
FINAL_OUTPUT_ROOT_DIR = os.path.join(DATA_PATH, "output_final")

# Đảm bảo các thư mục tồn tại
for d in [RESULT_DIR, DEPTH_ROOT_DIR, GEOJSON_ROOT_DIR, FINAL_OUTPUT_ROOT_DIR]:
    os.makedirs(d, exist_ok=True)

# ==========================================
# 2. IMPORT MODULES
# ==========================================
try:
    import create_simulation
    import download_result
    import calculate_depth
    # Import các module trong subfolder mapping
    import mapping.extract_geojson_full
    import mapping.merge_geojson
    import mapping.mapping_geojson
    import mapping.upload_minio
    print("✅ Import modules thành công!")
except ImportError as e:
    print(f"❌ Lỗi Import: {e}")
    print(f"👉 Kiểm tra lại đường dẫn SCRIPTS_PATH: {SCRIPTS_PATH}")
    sys.exit(1)

# ==========================================
# 3. HÀM CHẠY PIPELINE
# ==========================================
def run_pipeline(skip_sim=False, manual_sim_id=None, manual_nc_path=None):
    print("\n🚀 --- BẮT ĐẦU TEST PIPELINE (LOCAL) ---")

    # ---------------------------------------------------------
    # STEP 1: TRIGGER SIMULATION
    # ---------------------------------------------------------
    sim_id = manual_sim_id
    if not skip_sim:
        print("\n[1/7] 🚀 Triggering Simulation...")
        sim_id, _ = create_simulation.run_forecast_process(state_file_path=STATE_FILE)
        if not sim_id:
            print("❌ Failed to create simulation.")
            return
        print(f"✅ Simulation ID: {sim_id}")
    else:
        print(f"\n[1/7] ⏭️ Skip Simulation. Using Sim ID: {sim_id}")

    # ---------------------------------------------------------
    # STEP 2: DOWNLOAD RESULTS
    # ---------------------------------------------------------
    nc_path = manual_nc_path
    if sim_id and not nc_path:
        print(f"\n[2/7] ⬇️ Downloading results for Sim {sim_id}...")
        nc_path = download_result.run_download(sim_id, output_dir=RESULT_DIR)
        if not nc_path:
            print("❌ Download failed.")
            return
    elif nc_path:
        print(f"\n[2/7] ⏭️ Using existing NC file: {nc_path}")
    else:
        print("❌ Không có Sim ID và không có NC path. Dừng.")
        return

    print(f"✅ NC Path: {nc_path}")

    # ---------------------------------------------------------
    # STEP 3: CALCULATE DEPTH
    # ---------------------------------------------------------
    print("\n[3/7] ⚙️ Calculating Depth...")
    # Lưu ý: DAG dùng hardcode path, ở đây ta dùng path động từ bước 2 cho linh hoạt
    # output_depth_dir = calculate_depth.run_calculate_depth(
    #     grid_path=INPUT_GRID,
    #     nc_path=nc_path,
    #     dem_path=INPUT_DEM,
    #     output_dir=DEPTH_ROOT_DIR,
    # )
    # print(f"✅ Depth Output Dir: {output_depth_dir}")
    
    output_depth_dir = "data/mapping/output_depths/3543ec7c"
    
    # ---------------------------------------------------------
    # STEP 4: EXTRACT GEOJSON FULL
    # ---------------------------------------------------------
    print(f"\n[4/7] 🗺️ Extracting GeoJSON from: {output_depth_dir}")
    
    current_uuid = os.path.basename(str(output_depth_dir))
    output_geojson_dir = os.path.join(GEOJSON_ROOT_DIR, current_uuid)
    
    # Gọi module mapping.extract_geojson_full
    mapping.extract_geojson_full.run_extract_geojson(
        input_dir=str(output_depth_dir), 
        output_dir=str(output_geojson_dir)
    )
    print(f"✅ GeoJSON Dir: {output_geojson_dir}")

    # ---------------------------------------------------------
    # STEP 5: MERGE GEOJSON
    # ---------------------------------------------------------
    print(f"\n[5/7] ☁️ Merging GeoJSONs...")
    
    merged_file = mapping.merge_geojson.run_merge(
        geojson_dir=output_geojson_dir,
        output_dir=FINAL_OUTPUT_ROOT_DIR
    )
    
    if not merged_file:
        print("❌ Merge failed.")
        return
    print(f"✅ Merged File: {merged_file}")

    # ---------------------------------------------------------
    # STEP 6: MAPPING FLOOD -> ROADS
    # ---------------------------------------------------------
    print(f"\n[6/7] 🗺️ Mapping Flood to Roads...")
    
    mapping_output_dir = os.path.dirname(merged_file)
    mapping_output_file = os.path.join(
        mapping_output_dir,
        "road_flood_timeseries_generated.geojson"
    )
    
    if not os.path.exists(ROADS_GEOJSON_PATH):
        print(f"⚠️ Warning: Không tìm thấy file đường: {ROADS_GEOJSON_PATH}")
        print("   -> Bỏ qua bước Mapping.")
        final_upload_file = merged_file # Upload file merge nếu không map được
    else:
        final_upload_file = mapping.mapping_geojson.build_road_flood_timeseries_geojson(
            road_path=ROADS_GEOJSON_PATH,   
            flood_path=merged_file,
            out_path=mapping_output_file,
            buffer_deg=0.0002,
            target_epsg=4326,
        )
        print(f"✅ Mapping Done: {final_upload_file}")

    # ---------------------------------------------------------
    # STEP 7: UPLOAD MINIO
    # ---------------------------------------------------------
    print(f"\n[7/7] ☁️ Uploading to MinIO...")
    
    # Upload file kết quả cuối cùng (Mapping file)
    # Có thể truyền geojson_dir vào để cleanup nếu muốn
    result = mapping.upload_minio.run_upload(
        file_path=final_upload_file,
        geojson_dir_to_clean=output_geojson_dir, 
        tif_dir_to_clean=None, 
        delete_local_file_after_upload=False, # Để False khi test để kiểm tra file
    )

    if result:
        print(f"🎉 SUCCESS! Uploaded: {result['bucket']}/{result['object_name']}")
    else:
        print("❌ Upload failed.")

# ==========================================
# 4. MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    # CÁCH DÙNG:
    
    # CASE 1: Chạy full từ đầu (Tạo Sim -> ... -> Upload)
    # run_pipeline()

    # CASE 2: Đã có file NC (bỏ qua chạy Sim và Download), chỉ chạy xử lý ảnh
    # Thay đường dẫn bên dưới bằng file thực tế trên máy bạn
    EXISTING_NC = "data/mapping/results/results_3di.nc"
    
    if os.path.exists(EXISTING_NC):
        run_pipeline(skip_sim=True, manual_nc_path=EXISTING_NC)
    else:
        print("⚠️ Không tìm thấy file NC mẫu, sẽ chạy full pipeline...")
        run_pipeline(skip_sim=False)
