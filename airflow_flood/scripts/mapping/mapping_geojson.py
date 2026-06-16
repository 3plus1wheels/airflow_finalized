import os
import json
import fiona
import fiona.vfs

# Monkey patch for fiona 1.9+ compatibility with older geopandas
if not hasattr(fiona, "path"):
    fiona.path = fiona.vfs

import geopandas as gpd
from shapely.geometry import mapping


def build_road_flood_timeseries_geojson(
    road_path: str,
    flood_path: str,
    out_path: str,
    target_epsg: int = 4326,
    road_name_cols=("name", "@id", "road_name"),
    time_key_contains: str = "T",
    round_depth: int = 3,
    verbose: bool = True,
) -> str:
    """
    Logic:
    1) Load roads + flood
    2) CRS về EPSG:4326
    3) Dùng spatial index của flood để lấy candidate polygon theo bbox của road
    4) Với từng flood polygon giao road: intersection => segment LineString/MultiLineString
    5) Timeseries lấy trực tiếp theo các cột time chứa 'T' trong flood_row (không average)
    6) Safe road_name + safe export allow_nan=False

    Returns:
        str: out_path
    """

    # ==============================
    # 1. LOAD DATA
    # ==============================
    roads = gpd.read_file(road_path)
    flood = gpd.read_file(flood_path)

    roads = roads.to_crs(epsg=target_epsg)
    flood = flood.to_crs(epsg=target_epsg)

    if verbose:
        print("Loaded roads:", len(roads))
        print("Loaded flood cells:", len(flood))

    # ==============================
    # 2. SPATIAL INDEX (FLOOD)
    # ==============================
    flood_sindex = flood.sindex

    result_features = []

    # ==============================
    # helpers
    # ==============================
    def _is_nan(x) -> bool:
        try:
            return x != x
        except Exception:
            return False

    def _safe_float(x):
        if x is None or _is_nan(x):
            return None
        try:
            return float(x)
        except Exception:
            return None

    # ==============================
    # 3. SPLIT ROAD BY FLOOD (INTERSECTION)
    # ==============================
    for road_id, road_row in roads.iterrows():
        road_geom = road_row.geometry
        if road_geom is None or road_geom.is_empty:
            continue

        # Lấy index các polygon có bbox giao nhau
        candidate_idx = list(flood_sindex.intersection(road_geom.bounds))
        if not candidate_idx:
            continue

        # Safe road name
        road_name = None
        for c in road_name_cols:
            if c in road_row and road_row.get(c):
                road_name = road_row.get(c)
                break
        if not road_name:
            road_name = f"road_{road_id}"
        road_name = str(road_name)

        for idx in candidate_idx:
            flood_row = flood.iloc[idx]
            flood_geom = flood_row.geometry
            if flood_geom is None or flood_geom.is_empty:
                continue

            if not road_geom.intersects(flood_geom):
                continue

            intersection = road_geom.intersection(flood_geom)
            if intersection.is_empty:
                continue

            if intersection.geom_type == "MultiLineString":
                segments = list(intersection.geoms)
            elif intersection.geom_type == "LineString":
                segments = [intersection]
            else:
                # intersection ra Point/GeometryCollection... thì bỏ
                continue

            # Build timeseries trực tiếp từ flood_row
            timeseries = []
            for key, value in flood_row.items():
                if key in ("geometry",):
                    continue
                if time_key_contains in str(key):
                    v = _safe_float(value)
                    if v is None:
                        continue
                    timeseries.append({"time": str(key), "depth": round(v, round_depth)})

            if not timeseries:
                continue

            timeseries = sorted(timeseries, key=lambda x: x["time"])

            for segment in segments:
                if segment is None or segment.is_empty:
                    continue

                feature = {
                    "type": "Feature",
                    "geometry": mapping(segment),
                    "properties": {
                        "road_name": road_name,
                        "timeseries": timeseries,
                        # optional debug fields (bỏ comment nếu cần)
                        # "road_id": int(road_id) if str(road_id).isdigit() else str(road_id),
                        # "flood_idx": int(idx),
                    },
                }
                result_features.append(feature)

    # ==============================
    # 4. EXPORT (NO NaN)
    # ==============================
    output = {"type": "FeatureCollection", "features": result_features}

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, allow_nan=False)

    if verbose:
        print(f"✅ Done! File saved safely: {out_path} | features: {len(result_features)}")

    return out_path
