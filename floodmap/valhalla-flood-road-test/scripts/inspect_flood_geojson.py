#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from flood_utils import DATA_FILE, available_timesteps, bbox_for_geojson, load_geojson


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect flood-road GeoJSON.")
    parser.add_argument("--file", default=str(DATA_FILE))
    args = parser.parse_args()

    path = Path(args.file)
    data = load_geojson(path)
    errors: list[str] = []

    if data.get("type") != "FeatureCollection":
        errors.append("top-level type is not FeatureCollection")

    geom_types = Counter()
    bad_timeseries = 0
    bad_depth = 0
    coordinate_order_warnings = 0

    for idx, feature in enumerate(data.get("features", [])):
        geometry = feature.get("geometry", {})
        geom_type = geometry.get("type")
        geom_types[geom_type] += 1
        if geom_type != "LineString":
            errors.append(f"feature {idx}: geometry is {geom_type}, expected LineString")
            continue
        coords = geometry.get("coordinates") or []
        for coord in coords:
            if len(coord) < 2:
                errors.append(f"feature {idx}: coordinate has fewer than 2 values")
                continue
            lon, lat = coord[:2]
            if not (90 <= abs(lon) <= 180 and -90 <= lat <= 90):
                coordinate_order_warnings += 1
        timeseries = feature.get("properties", {}).get("timeseries")
        if not isinstance(timeseries, list) or not timeseries:
            bad_timeseries += 1
            continue
        for item in timeseries:
            if "time" not in item or "depth" not in item:
                bad_timeseries += 1
                continue
            if not isinstance(item.get("depth"), (int, float)):
                bad_depth += 1

    min_lon, min_lat, max_lon, max_lat = bbox_for_geojson(data)

    print(f"Loaded {path.name}")
    print(f"Feature count: {len(data.get('features', []))}")
    print("Geometry types: " + ", ".join(f"{key}: {value}" for key, value in geom_types.items()))
    print("Available time steps:")
    for time in available_timesteps(data):
        print(f"- {time}")
    print("Depth unit: meters assumed")
    print("Coordinate order: [longitude, latitude] assumed")
    print("Bounding box:")
    print(f"- min lon: {min_lon}")
    print(f"- max lon: {max_lon}")
    print(f"- min lat: {min_lat}")
    print(f"- max lat: {max_lat}")
    print("Validation:")
    print(f"- missing/invalid timeseries items: {bad_timeseries}")
    print(f"- non-numeric depths: {bad_depth}")
    print(f"- coordinate order warnings: {coordinate_order_warnings}")

    if errors:
        print("Errors:")
        for error in errors[:20]:
            print(f"- {error}")
        if len(errors) > 20:
            print(f"- ... {len(errors) - 20} more")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
