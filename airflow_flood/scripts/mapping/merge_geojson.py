import glob
import json
import os

import fiona
import fiona.vfs
import pandas as pd

# Monkey patch for fiona 1.9+ compatibility with older geopandas.
if not hasattr(fiona, "path"):
    fiona.path = fiona.vfs

# Monkey patch for pandas 2.0+ compatibility with older geopandas.
if not hasattr(pd, "Int64Index"):
    pd.Int64Index = pd.Index
if not hasattr(pd, "Float64Index"):
    pd.Float64Index = pd.Index

import geopandas as gpd


def write_empty_geojson(output_file: str) -> bool:
    out_dir = os.path.dirname(output_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as geojson_file:
        json.dump({"type": "FeatureCollection", "features": []}, geojson_file)
    print(f"Empty merged GeoJSON created: {output_file}")
    return True


def merge_geojsons(input_dir: str, output_file: str) -> bool:
    print(f"Reading GeoJSON files from: {input_dir}")

    if not input_dir:
        print("Input directory is None.")
        return False

    files = sorted(glob.glob(os.path.join(input_dir, "depth_*.geojson")))
    if not files:
        print("No depth_*.geojson files found. Writing empty merged GeoJSON.")
        return write_empty_geojson(output_file)

    all_dfs = []
    print(f"Found {len(files)} GeoJSON files. Processing...")

    for path in files:
        try:
            filename = os.path.basename(path)
            raw_name = filename.replace("depth_", "").replace(".geojson", "")

            if len(raw_name) == 15 and "_" in raw_name:
                col_name = (
                    f"{raw_name[:4]}-{raw_name[4:6]}-{raw_name[6:8]}"
                    f"T{raw_name[9:11]}:{raw_name[11:13]}:{raw_name[13:]}"
                )
            else:
                col_name = raw_name

            with open(path, "r", encoding="utf-8") as geojson_file:
                data = json.load(geojson_file)

            if not data.get("features"):
                print(f"File {filename} has no features, treating as empty flood result.")
                continue

            gdf = gpd.GeoDataFrame.from_features(data["features"])
            gdf.set_crs(epsg=4326, inplace=True)

            if "depth" not in gdf.columns:
                print(f"File {filename} is missing the depth column, skipping.")
                continue

            gdf = gdf[["geometry", "depth"]].rename(columns={"depth": col_name})
            gdf["geom_wkt"] = gdf["geometry"].apply(lambda geom: geom.wkt)
            all_dfs.append(pd.DataFrame(gdf.drop(columns="geometry")))

        except Exception as exc:
            print(f"Error reading {path}: {exc}")

    if not all_dfs:
        print("No valid GeoJSON dataframes to merge. Writing empty merged GeoJSON.")
        return write_empty_geojson(output_file)

    print(f"Merging {len(all_dfs)} dataframes...")
    master_df = pd.concat(all_dfs, ignore_index=True)
    merged_df = master_df.groupby("geom_wkt").first().reset_index().fillna(0)

    print(f"Rebuilding merged GeoJSON with {len(merged_df)} polygons...")
    geometry = gpd.GeoSeries.from_wkt(merged_df["geom_wkt"])
    final_gdf = gpd.GeoDataFrame(merged_df.drop(columns="geom_wkt"), geometry=geometry)
    final_gdf.set_crs(epsg=4326, inplace=True)

    out_dir = os.path.dirname(output_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    final_gdf.to_file(output_file, driver="GeoJSON")
    print(f"Merged GeoJSON created: {output_file}")
    return True


def run_merge(
    geojson_dir: str,
    output_dir: str,
    tif_dir_to_clean: str = None,
    run_ts: str = None,
):
    """
    Merge extracted depth GeoJSON files into a local flood GeoJSON.

    Uploading is intentionally handled by the DAG's final upload task after
    road mapping creates flood_road_<run_ts>.geojson.
    """
    print("--- START MERGE ---")

    if not geojson_dir:
        print("Merge failed: geojson_dir is None.")
        return None

    if not run_ts:
        run_ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

    merged_path = os.path.join(output_dir, run_ts, f"flood_{run_ts}.geojson")

    if merge_geojsons(geojson_dir, merged_path):
        print(f"Merge complete. Local file: {merged_path}")
        return merged_path

    print("Merge failed.")
    return None
