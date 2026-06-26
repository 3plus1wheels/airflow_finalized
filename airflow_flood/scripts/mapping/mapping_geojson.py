import json
import os

import fiona
import fiona.vfs

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
    roads = gpd.read_file(road_path)
    flood = gpd.read_file(flood_path)

    if flood.empty:
        raise ValueError(f"Flood GeoJSON has no features: {flood_path}")

    roads = roads.to_crs(epsg=target_epsg)
    flood = flood.to_crs(epsg=target_epsg)

    if verbose:
        print("Loaded roads:", len(roads))
        print("Loaded flood cells:", len(flood))

    flood_sindex = flood.sindex
    result_features = []

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

    for road_id, road_row in roads.iterrows():
        road_geom = road_row.geometry
        if road_geom is None or road_geom.is_empty:
            continue

        candidate_idx = list(flood_sindex.intersection(road_geom.bounds))
        if not candidate_idx:
            continue

        road_name = None
        for column in road_name_cols:
            if column in road_row and road_row.get(column):
                road_name = road_row.get(column)
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
                continue

            timeseries = []
            for key, value in flood_row.items():
                if key in ("geometry",):
                    continue
                if time_key_contains in str(key):
                    safe_value = _safe_float(value)
                    if safe_value is None:
                        continue
                    timeseries.append(
                        {"time": str(key), "depth": round(safe_value, round_depth)}
                    )

            if not timeseries:
                continue

            timeseries = sorted(timeseries, key=lambda item: item["time"])

            for segment in segments:
                if segment is None or segment.is_empty:
                    continue

                result_features.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(segment),
                        "properties": {
                            "road_name": road_name,
                            "timeseries": timeseries,
                        },
                    }
                )

    output = {"type": "FeatureCollection", "features": result_features}

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as output_file:
        json.dump(output, output_file, ensure_ascii=False, indent=2, allow_nan=False)

    if verbose:
        print(f"Done. File saved: {out_path} | features: {len(result_features)}")

    return out_path
