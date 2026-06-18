import json
import os

import billiard as multiprocessing
import fiona
import fiona.vfs
import pandas as pd
import rasterio
from rasterio.warp import transform_bounds


if not hasattr(pd, "Int64Index"):
    pd.Int64Index = pd.Index
if not hasattr(pd, "Float64Index"):
    pd.Float64Index = pd.Index

if not hasattr(fiona, "path"):
    fiona.path = fiona.vfs

from shapely.geometry import box, mapping


SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", 1))
MIN_DEPTH_THRESHOLD = float(os.getenv("MIN_DEPTH_THRESHOLD", 0.05))


def get_available_cpus():
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return multiprocessing.cpu_count()


MAX_WORKERS = int(os.getenv("MAX_WORKERS", get_available_cpus()))


def write_empty_geojson(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": []}, f)


def write_geojson_feature(out_file, feature, is_first):
    if not is_first:
        out_file.write(",\n")
    json.dump(feature, out_file, ensure_ascii=False, allow_nan=False)
    return False


def worker_tif_to_geojson(args):
    input_tif, output_geojson = args

    try:
        with rasterio.open(input_tif) as src:
            data = src.read(1)
            transform = src.transform
            nodata = src.nodata
            target_crs = "EPSG:4326"
            should_transform = src.crs and str(src.crs).upper() != target_crs
            count = 0
            first = True
            os.makedirs(os.path.dirname(output_geojson) or ".", exist_ok=True)

            with open(output_geojson, "w", encoding="utf-8") as out_file:
                out_file.write('{"type":"FeatureCollection","features":[\n')
                for row in range(0, src.height, SAMPLE_RATE):
                    for col in range(0, src.width, SAMPLE_RATE):
                        block = data[row : row + SAMPLE_RATE, col : col + SAMPLE_RATE]
                        if block.size == 0:
                            continue

                        if nodata is None:
                            valid_depths = block[block > MIN_DEPTH_THRESHOLD]
                        else:
                            valid_depths = block[
                                (block != nodata) & (block > MIN_DEPTH_THRESHOLD)
                            ]
                        if valid_depths.size == 0:
                            continue

                        avg_depth = round(float(valid_depths.mean()), 2)
                        left, top = transform * (col, row)
                        col_end = min(col + SAMPLE_RATE, src.width)
                        row_end = min(row + SAMPLE_RATE, src.height)
                        right, bottom = transform * (col_end, row_end)

                        if should_transform:
                            try:
                                left, bottom, right, top = transform_bounds(
                                    src.crs,
                                    target_crs,
                                    left,
                                    bottom,
                                    right,
                                    top,
                                    densify_pts=2,
                                )
                            except Exception:
                                pass

                        feature = {
                            "type": "Feature",
                            "geometry": mapping(box(left, bottom, right, top)),
                            "properties": {"depth": avg_depth},
                        }
                        first = write_geojson_feature(out_file, feature, first)
                        count += 1

                out_file.write("\n]}")

            if count == 0:
                write_empty_geojson(output_geojson)
                return f"Created empty GeoJSON: {os.path.basename(output_geojson)}"

            return f"Created: {os.path.basename(output_geojson)} ({count} cells)"

    except Exception as exc:
        return f"Error converting {os.path.basename(input_tif)}: {exc}"


def run_extract_geojson(input_dir, output_dir):
    print("--- START EXTRACT GEOJSON ---")
    print(f"Input: {input_dir}")
    print(f"Output: {output_dir}")
    print(
        f"Config: sample_rate={SAMPLE_RATE}, min_depth={MIN_DEPTH_THRESHOLD}, processes={MAX_WORKERS}"
    )

    if not os.path.exists(input_dir):
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    os.makedirs(output_dir, exist_ok=True)

    files = sorted(f for f in os.listdir(input_dir) if f.endswith(".tif"))
    if not files:
        raise FileNotFoundError(f"No .tif files found in {input_dir}")

    tasks = []
    for filename in files:
        in_path = os.path.join(input_dir, filename)
        out_name = f"{os.path.splitext(filename)[0]}.geojson"
        out_path = os.path.join(output_dir, out_name)
        tasks.append((in_path, out_path))

    if MAX_WORKERS <= 1:
        for task in tasks:
            print(worker_tif_to_geojson(task))
    else:
        with multiprocessing.Pool(processes=MAX_WORKERS, maxtasksperchild=1) as pool:
            results = pool.map(worker_tif_to_geojson, tasks)
            for result in results:
                print(result)

    created = [
        f for f in os.listdir(output_dir)
        if f.endswith(".geojson") and os.path.isfile(os.path.join(output_dir, f))
    ]
    if not created:
        raise RuntimeError(f"GeoJSON extraction produced no files in {output_dir}")

    print(f"GeoJSON conversion complete. Files: {len(created)}")
