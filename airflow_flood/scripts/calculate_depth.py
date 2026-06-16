import os
import re
import uuid
import billiard as multiprocessing
from datetime import datetime, timedelta
from osgeo import gdal
from threedidepth import calculate_waterdepth
from threedigrid.admin.gridresultadmin import GridH5ResultAdmin

import fiona
import fiona.vfs

if not hasattr(fiona, 'path'):
    fiona.path = fiona.vfs


CLEAN_DATA = True


def get_time_from_tif_and_clean(tif_path):
    """Đọc giờ từ TIF (UTC) -> cộng 7 tiếng -> Làm sạch dữ liệu"""
    time_str_vn = None
    try:
        ds = gdal.Open(tif_path, 1)
        if ds is None:
            return None
        band = ds.GetRasterBand(1)

        desc = band.GetDescription()
        match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", desc)
        if match:
            dt_utc = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            dt_vn = dt_utc + timedelta(hours=7)
            time_str_vn = dt_vn.strftime("%Y%m%d_%H%M%S")

        if CLEAN_DATA:
            data = band.ReadAsArray()
            nodata_val = band.GetNoDataValue()
            if data.max() > 0:
                if nodata_val is not None:
                    data[data == nodata_val] = 0
                    if nodata_val > 1000:
                        data[data > 1000] = 0
                data[data < 0] = 0
                data[data > 100] = 0
                band.WriteArray(data)
                band.SetNoDataValue(0)
        ds.FlushCache()
        ds = None
    except Exception as e:
        print(f"⚠️ Warning {os.path.basename(tif_path)}: {e}")
    return time_str_vn


def process_single_step(args):
    """Worker chạy trên từng process (đa tiến trình)"""
    step_index, grid_path, nc_path, dem_path, output_dir = args

    temp_filename = f"temp_{step_index:04d}.tif"
    temp_path = os.path.join(output_dir, temp_filename)

    try:

        calculate_waterdepth(
            gridadmin_path=grid_path,
            results_3di_path=nc_path,
            dem_path=dem_path,
            waterdepth_path=temp_path,
            calculation_steps=[step_index],
        )

        timestamp_name = get_time_from_tif_and_clean(temp_path)
        if timestamp_name:
            final_name = f"depth_{timestamp_name}.tif"
            final_path = os.path.join(output_dir, final_name)
            if os.path.exists(final_path):
                os.remove(final_path)
            os.rename(temp_path, final_path)
            return f"✅ {final_name}"
        else:
            return f"⚠️ {temp_filename} (No Time)"
    except Exception as e:
        return f"❌ Step {step_index}: {e}"


def run_calculate_depth(grid_path, nc_path, dem_path, output_dir):

    run_uuid = str(uuid.uuid4())[:8]
    current_output_dir = os.path.join(output_dir, run_uuid)

    if not os.path.exists(current_output_dir):
        os.makedirs(current_output_dir)
        print(f"📂 Created Output Dir: {current_output_dir}")

    try:
        ga = GridH5ResultAdmin(grid_path, nc_path)
        total_steps = len(ga.nodes.timestamps)
        ga = None
        print(f"🔄 Total Steps: {total_steps}")
    except Exception as e:
        print(f"❌ Error reading inputs: {e}")
        raise e

    # Đóng gói tham số cho từng process
    tasks = [(i, grid_path, nc_path, dem_path, current_output_dir) for i in range(total_steps)]
    
    # Sử dụng tối đa CPU core có sẵn thay vì giới hạn 8
    try:
        # Lấy số CPU được phép sử dụng (trong container)
        default_workers = len(os.sched_getaffinity(0))
    except AttributeError:
        default_workers = multiprocessing.cpu_count()
    max_workers = int(os.getenv("MAX_WORKERS", default_workers))

    print(f"🚀 Calculating on {max_workers} processes (Multiprocessing)...")
    # Sử dụng billiard.Pool, một nhánh của multiprocessing.Pool, an toàn để sử dụng
    # trong các tiến trình daemon (như Celery workers) mà không cần các giải pháp tạm thời.
    with multiprocessing.Pool(processes=max_workers) as pool:
        results = pool.map(process_single_step, tasks)
        for res in results:
            print(res)

    print(f"🎉 Calculate Depth Done! Saved to: {current_output_dir}")
    return current_output_dir
