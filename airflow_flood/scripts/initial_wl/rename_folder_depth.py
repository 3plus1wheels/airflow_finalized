import os
import shutil
from datetime import datetime


# ==============================================================================
# AIRFLOW ENTRYPOINT
# ==============================================================================

def run_rename_depth(output_uuid_dir, initial_wl_timestamp):
    print("📡 START rename depth folder")
    print(f"📂 Current depth directory: {output_uuid_dir}")
    print(f"🕒 Initial WL timestamp: {initial_wl_timestamp}")

    if not output_uuid_dir:
        raise ValueError("output_uuid_dir is empty")

    if not initial_wl_timestamp:
        raise ValueError("initial_wl_timestamp is empty")

    if not os.path.exists(output_uuid_dir):
        raise FileNotFoundError(f"Depth directory not found: {output_uuid_dir}")

    if not os.path.isdir(output_uuid_dir):
        raise NotADirectoryError(f"Path is not a directory: {output_uuid_dir}")

    tif_files = [
        f for f in os.listdir(output_uuid_dir)
        if f.lower().endswith(".tif")
    ]

    if not tif_files:
        raise FileNotFoundError(f"No .tif files found in {output_uuid_dir}")

    timestamp_depth = datetime.now().strftime("%Y%m%d_%H%M%S")

    parent_dir = os.path.dirname(output_uuid_dir)

    new_folder_name = f"depth_{timestamp_depth}_initialwl_{initial_wl_timestamp}"
    new_output_dir = os.path.join(parent_dir, new_folder_name)

    if os.path.exists(new_output_dir):
        raise FileExistsError(f"Target folder already exists: {new_output_dir}")

    print(f"📦 Found {len(tif_files)} TIF files")
    print(f"🔁 Rename folder:")
    print(f"   FROM: {output_uuid_dir}")
    print(f"   TO:   {new_output_dir}")

    os.rename(output_uuid_dir, new_output_dir)

    print("✅ Rename depth folder complete")
    print(f"📂 New depth directory: {new_output_dir}")

    return new_output_dir


if __name__ == "__main__":
    test_dir = os.getenv("DEPTH_OUTPUT_DIR")
    test_initial_wl_timestamp = os.getenv("INITIAL_WL_TIMESTAMP")

    if not test_dir:
        raise ValueError("Missing DEPTH_OUTPUT_DIR")

    if not test_initial_wl_timestamp:
        raise ValueError("Missing INITIAL_WL_TIMESTAMP")

    run_upload_depth(test_dir, test_initial_wl_timestamp)