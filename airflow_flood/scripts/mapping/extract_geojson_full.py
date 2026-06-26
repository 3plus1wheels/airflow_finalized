import os

import billiard as multiprocessing
import fiona
import fiona.vfs
import pandas as pd
import rasterio

if not hasattr(pd, "Int64Index"):
    pd.Int64Index = pd.Index
if not hasattr(pd, "Float64Index"):
    pd.Float64Index = pd.Index

if not hasattr(fiona, "path"):
    fiona.path = fiona.vfs

import geopandas as gpd
from shapely.geometry import box


SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", 1))


def get_available_cpus():
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return multiprocessing.cpu_count()


MAX_WORKERS = int(os.getenv("MAX_WORKERS", get_available_cpus()))


def worker_tif_to_geojson(args):
    input_tif, output_geojson = args

    try:
        with rasterio.open(input_tif) as src:
            data = src.read(1)
            transform = src.transform
            nodata = src.nodata

            cells = []

            for row in range(0, src.height, SAMPLE_RATE):
                for col in range(0, src.width, SAMPLE_RATE):
                    depth_value = data[row, col]

                    if nodata is None or depth_value != nodata:
                        left, top = transform * (col, row)
                        right, bottom = transform * (
                            col + SAMPLE_RATE,
                            row + SAMPLE_RATE,
                        )

                        poly = box(left, bottom, right, top)
                        cells.append(
                            {
                                "geometry": poly,
                                "properties": {"depth": round(float(depth_value), 2)},
                            }
                        )

            if not cells:
                return f"Skipped empty/low-depth raster: {os.path.basename(input_tif)}"

            gdf = gpd.GeoDataFrame.from_features(cells)

            if src.crs:
                gdf.set_crs(src.crs, allow_override=True, inplace=True)
                try:
                    gdf = gdf.to_crs(epsg=4326)
                except Exception:
                    pass

            gdf.to_file(output_geojson, driver="GeoJSON")
            return f"Created: {os.path.basename(output_geojson)} ({len(gdf)} cells)"

    except Exception as exc:
        return f"Error converting {os.path.basename(input_tif)}: {exc}"


def run_extract_geojson(input_dir, output_dir):
    print("--- START EXTRACT GEOJSON (MULTIPROCESSING) ---")
    print(f"Input: {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Config: sample_rate={SAMPLE_RATE}, processes={MAX_WORKERS}")

    if not os.path.exists(input_dir):
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    files = sorted([f for f in os.listdir(input_dir) if f.endswith(".tif")])

    if not files:
        print("No .tif files found.")
        return

    print(f"Found {len(files)} TIF files. Converting...")

    tasks = []
    for filename in files:
        in_path = os.path.join(input_dir, filename)
        out_name = f"{os.path.splitext(filename)[0]}.geojson"
        out_path = os.path.join(output_dir, out_name)
        tasks.append((in_path, out_path))

    with multiprocessing.Pool(processes=MAX_WORKERS) as pool:
        results = pool.map(worker_tif_to_geojson, tasks)
        for result in results:
            print(result)

    print("GeoJSON conversion complete.")
