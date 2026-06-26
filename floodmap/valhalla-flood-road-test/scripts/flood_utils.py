#!/usr/bin/env python3
"""Shared helpers for Valhalla flood-road linear_cost_factors tests."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "flood_road_20260522T103000.geojson"
REQUESTS_DIR = ROOT / "requests"
RESPONSES_DIR = ROOT / "responses"
VALHALLA_URL = "http://localhost:8002"
DEFAULT_TIME = "2026-05-22T18:00:00"
DEFAULT_COSTING = "motor_scooter"
DEFAULT_ORIGIN = {"lat": 21.0214, "lon": 105.7610}
DEFAULT_DESTINATION = {"lat": 21.0225, "lon": 105.7650}
VEHICLE_PROFILES = {
    "motorbike": {
        "costing": "motor_scooter",
        "threshold_cm": 20,
        "label_vi": "Xe máy",
        "label_en": "Motorbike",
    },
    "car": {
        "costing": "auto",
        "threshold_cm": 30,
        "label_vi": "Ô tô",
        "label_en": "Car",
    },
    "truck": {
        "costing": "truck",
        "threshold_cm": 50,
        "label_vi": "Xe tải",
        "label_en": "Truck",
    },
}


@dataclass(frozen=True)
class FloodFeature:
    geometry: dict[str, Any]
    road_name: str
    time: str
    depth_m: float
    depth_cm: float
    factor: float


def load_geojson(path: Path = DATA_FILE) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def motorbike_factor_from_depth_m(depth_m: float) -> float:
    if depth_m < 0.03:
        return 1
    if depth_m < 0.05:
        return 2
    if depth_m < 0.10:
        return 8
    if depth_m < 0.15:
        return 25
    if depth_m < 0.20:
        return 60
    return 100


def vehicle_profile(vehicle_type: str = "motorbike") -> dict[str, Any]:
    return VEHICLE_PROFILES.get(vehicle_type, VEHICLE_PROFILES["motorbike"])


def vehicle_costing(vehicle_type: str = "motorbike") -> str:
    return str(vehicle_profile(vehicle_type)["costing"])


def vehicle_threshold_cm(vehicle_type: str = "motorbike") -> float:
    return float(vehicle_profile(vehicle_type)["threshold_cm"])


def vehicle_types() -> list[str]:
    return list(VEHICLE_PROFILES)


def factor_from_depth_m(depth_m: float, vehicle_type: str = "motorbike") -> float:
    threshold_cm = max(vehicle_threshold_cm(vehicle_type), 1.0)
    depth_cm = max(depth_m * 100, 0.0)
    if depth_cm < threshold_cm * 0.15:
        return 1
    if depth_cm < threshold_cm * 0.25:
        return 2
    if depth_cm < threshold_cm * 0.50:
        return 8
    if depth_cm < threshold_cm * 0.75:
        return 25
    if depth_cm < threshold_cm:
        return 60
    return 100


def feature_depth_at_time(feature: dict[str, Any], time_step: str) -> float | None:
    for item in feature.get("properties", {}).get("timeseries", []):
        if item.get("time") == time_step:
            depth = item.get("depth")
            if isinstance(depth, (int, float)):
                return float(depth)
    return None


def available_timesteps(geojson: dict[str, Any]) -> list[str]:
    steps: set[str] = set()
    for feature in geojson.get("features", []):
        for item in feature.get("properties", {}).get("timeseries", []):
            time = item.get("time")
            if isinstance(time, str):
                steps.add(time)
    return sorted(steps)


def bbox_for_geojson(geojson: dict[str, Any]) -> tuple[float, float, float, float]:
    lons: list[float] = []
    lats: list[float] = []
    for feature in geojson.get("features", []):
        for lon, lat in feature.get("geometry", {}).get("coordinates", []):
            lons.append(float(lon))
            lats.append(float(lat))
    if not lons or not lats:
        raise ValueError("no LineString coordinates found")
    return min(lons), min(lats), max(lons), max(lats)


def build_flood_features(
    geojson: dict[str, Any],
    time_step: str,
    vehicle_type: str = "motorbike",
    include_factor_one: bool = False,
) -> list[FloodFeature]:
    features: list[FloodFeature] = []
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry", {})
        if geometry.get("type") != "LineString":
            continue
        depth_m = feature_depth_at_time(feature, time_step)
        if depth_m is None:
            continue
        factor = factor_from_depth_m(depth_m, vehicle_type)
        if factor <= 1 and not include_factor_one:
            continue
        props = feature.get("properties", {})
        features.append(
            FloodFeature(
                geometry=geometry,
                road_name=str(props.get("road_name") or props.get("name") or ""),
                time=time_step,
                depth_m=depth_m,
                depth_cm=depth_m * 100,
                factor=factor,
            )
        )
    return features


def to_linear_cost_factor_feature(item: FloodFeature, debug_props: bool = True) -> dict[str, Any]:
    props: dict[str, Any] = {"factor": item.factor}
    if debug_props:
        props.update(
            {
                "road_name": item.road_name,
                "depth_m": item.depth_m,
                "depth_cm": round(item.depth_cm, 2),
                "time": item.time,
            }
        )
    return {"type": "Feature", "geometry": item.geometry, "properties": props}


def _line_buffer_polygon(coordinates: list[Any], buffer_m: float) -> list[list[float]]:
    lats = [float(lat) for _, lat in coordinates]
    mid_lat = sum(lats) / len(lats)
    lon_m, lat_m = meters_per_degree(mid_lat)
    if not lon_m or not lat_m:
        return []

    origin_lon = float(coordinates[0][0])
    origin_lat = float(coordinates[0][1])
    points = [
        ((float(lon) - origin_lon) * lon_m, (float(lat) - origin_lat) * lat_m)
        for lon, lat in coordinates
    ]
    if len(points) < 2:
        x, y = points[0]
        corners = [
            (x - buffer_m, y - buffer_m),
            (x + buffer_m, y - buffer_m),
            (x + buffer_m, y + buffer_m),
            (x - buffer_m, y + buffer_m),
            (x - buffer_m, y - buffer_m),
        ]
    else:
        normals: list[tuple[float, float]] = []
        for index, (x, y) in enumerate(points):
            candidates: list[tuple[float, float]] = []
            for neighbor in (index - 1, index):
                if neighbor < 0 or neighbor >= len(points) - 1:
                    continue
                nx = points[neighbor + 1][0] - points[neighbor][0]
                ny = points[neighbor + 1][1] - points[neighbor][1]
                length = math.hypot(nx, ny)
                if length:
                    candidates.append((-ny / length, nx / length))
            avg_x = sum(item[0] for item in candidates)
            avg_y = sum(item[1] for item in candidates)
            avg_length = math.hypot(avg_x, avg_y)
            normals.append((avg_x / avg_length, avg_y / avg_length) if avg_length else (0.0, 1.0))

        left = [(x + nx * buffer_m, y + ny * buffer_m) for (x, y), (nx, ny) in zip(points, normals)]
        right = [(x - nx * buffer_m, y - ny * buffer_m) for (x, y), (nx, ny) in zip(points, normals)]
        corners = left + list(reversed(right)) + [left[0]]

    return [[origin_lon + x / lon_m, origin_lat + y / lat_m] for x, y in corners]


def to_flood_polygon_feature(item: FloodFeature, buffer_m: float = 22.0) -> dict[str, Any]:
    coordinates = item.geometry.get("coordinates", [])
    if not coordinates:
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {},
        }
    polygon = _line_buffer_polygon(coordinates, buffer_m)

    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [polygon],
        },
        "properties": {
            "road_name": item.road_name,
            "time": item.time,
            "depth_m": item.depth_m,
            "depth_cm": round(item.depth_cm, 2),
            "factor": item.factor,
            "source": "flood_road_buffer",
        },
    }


def dangerous_flood_features(features: list[FloodFeature], min_depth_m: float = 0.20) -> list[FloodFeature]:
    return [item for item in features if item.depth_m >= min_depth_m]


def exclude_locations_from_features(
    features: list[FloodFeature],
    max_points_per_feature: int = 3,
) -> list[dict[str, float]]:
    locations: list[dict[str, float]] = []
    seen: set[tuple[float, float]] = set()

    for item in features:
        coordinates = item.geometry.get("coordinates", [])
        if not coordinates:
            continue
        if max_points_per_feature <= 1 or len(coordinates) == 1:
            sample_indexes = [0]
        elif max_points_per_feature == 2:
            sample_indexes = [0, len(coordinates) - 1]
        else:
            sample_indexes = [0, len(coordinates) // 2, len(coordinates) - 1]

        for index in sample_indexes[:max_points_per_feature]:
            lon = float(coordinates[index][0])
            lat = float(coordinates[index][1])
            key = (lat, lon)
            if key in seen:
                continue
            seen.add(key)
            locations.append({"lat": lat, "lon": lon})

    return locations


def route_request(
    origin: dict[str, float] | None = None,
    destination: dict[str, float] | None = None,
    costing: str = DEFAULT_COSTING,
    linear_cost_factors: list[dict[str, Any]] | None = None,
    exclude_locations: list[dict[str, float]] | None = None,
    alternates: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "locations": [origin or DEFAULT_ORIGIN, destination or DEFAULT_DESTINATION],
        "costing": costing,
        "directions_options": {"units": "kilometers", "shape_format": "geojson"},
    }
    if linear_cost_factors is not None:
        payload["linear_cost_factors"] = linear_cost_factors
    if exclude_locations is not None:
        payload["exclude_locations"] = exclude_locations
    if alternates:
        payload["alternates"] = max(0, min(int(alternates), 2))
    return payload


def post_valhalla_route(payload: dict[str, Any], url: str = VALHALLA_URL, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{url.rstrip('/')}/route",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8")
            return {"ok": True, "status": res.status, "json": json.loads(body)}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": exc.code, "error": body}
    except Exception as exc:
        return {"ok": False, "status": None, "error": str(exc)}


def get_valhalla_status(url: str = VALHALLA_URL) -> dict[str, Any]:
    req = urllib.request.Request(f"{url.rstrip('/')}/status", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            body = res.read().decode("utf-8")
            return {"ok": True, "status": res.status, "json": json.loads(body)}
    except Exception as exc:
        return {"ok": False, "status": None, "error": str(exc)}


def version_tuple(version: str) -> tuple[int, int, int]:
    parts = []
    for part in version.split(".")[:3]:
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def route_summary(route_response: dict[str, Any]) -> dict[str, Any]:
    if not route_response.get("ok"):
        return {"ok": False, "error": route_response.get("error")}
    trip = route_response.get("json", {}).get("trip", {})
    summary = trip.get("summary", {})
    return {
        "ok": True,
        "distance_km": summary.get("length"),
        "duration_min": (summary.get("time") or 0) / 60 if summary.get("time") is not None else None,
        "shape": trip.get("legs", [{}])[0].get("shape"),
        "maneuver_streets": [
            maneuver.get("street_names") or maneuver.get("begin_street_names") or []
            for maneuver in trip.get("legs", [{}])[0].get("maneuvers", [])
        ],
    }


def decode_polyline(encoded: str | None, precision: int = 6) -> list[tuple[float, float]]:
    if isinstance(encoded, dict):
        return [
            (float(lon), float(lat))
            for lon, lat in encoded.get("coordinates", [])
        ]
    if not encoded:
        return []
    coords: list[tuple[float, float]] = []
    index = 0
    lat = 0
    lon = 0
    factor = 10**precision
    while index < len(encoded):
        result = 1
        shift = 0
        while True:
            b = ord(encoded[index]) - 63 - 1
            index += 1
            result += b << shift
            shift += 5
            if b < 0x1F:
                break
        lat += ~(result >> 1) if result & 1 else result >> 1
        result = 1
        shift = 0
        while True:
            b = ord(encoded[index]) - 63 - 1
            index += 1
            result += b << shift
            shift += 5
            if b < 0x1F:
                break
        lon += ~(result >> 1) if result & 1 else result >> 1
        coords.append((lon / factor, lat / factor))
    return coords


def meters_per_degree(lat: float) -> tuple[float, float]:
    lat_m = 111_320.0
    lon_m = 111_320.0 * math.cos(math.radians(lat))
    return lon_m, lat_m


def point_to_segment_distance_m(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    mid_lat = (p[1] + a[1] + b[1]) / 3
    lon_m, lat_m = meters_per_degree(mid_lat)
    px, py = p[0] * lon_m, p[1] * lat_m
    ax, ay = a[0] * lon_m, a[1] * lat_m
    bx, by = b[0] * lon_m, b[1] * lat_m
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx = ax + t * dx
    cy = ay + t * dy
    return math.hypot(px - cx, py - cy)


def segment_distance_m(a1: tuple[float, float], a2: tuple[float, float], b1: tuple[float, float], b2: tuple[float, float]) -> float:
    return min(
        point_to_segment_distance_m(a1, b1, b2),
        point_to_segment_distance_m(a2, b1, b2),
        point_to_segment_distance_m(b1, a1, a2),
        point_to_segment_distance_m(b2, a1, a2),
    )


def line_distance_m(line_a: list[tuple[float, float]], line_b: list[tuple[float, float]]) -> float:
    if len(line_a) < 2 or len(line_b) < 2:
        return float("inf")
    best = float("inf")
    for i in range(len(line_a) - 1):
        for j in range(len(line_b) - 1):
            best = min(best, segment_distance_m(line_a[i], line_a[i + 1], line_b[j], line_b[j + 1]))
    return best


def line_bbox(line: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    lons = [point[0] for point in line]
    lats = [point[1] for point in line]
    return min(lons), min(lats), max(lons), max(lats)


def bbox_intersects(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    pad_deg: float = 0.0,
) -> bool:
    return not (
        a[2] + pad_deg < b[0]
        or b[2] + pad_deg < a[0]
        or a[3] + pad_deg < b[1]
        or b[3] + pad_deg < a[1]
    )


def flood_exposure(
    route_lonlat: list[tuple[float, float]],
    flood_features: list[FloodFeature],
    threshold_m: float = 12.0,
) -> dict[str, Any]:
    crossed: list[FloodFeature] = []
    if len(route_lonlat) < 2:
        return {
            "crosses_flooded_road": False,
            "affected_road_count": 0,
            "max_depth_m": 0,
            "max_depth_cm": 0,
            "max_factor": 0,
            "roads": crossed,
        }
    route_bbox = line_bbox(route_lonlat)
    pad_deg = threshold_m / 111_320.0
    for item in flood_features:
        line = [(float(lon), float(lat)) for lon, lat in item.geometry.get("coordinates", [])]
        if len(line) < 2 or not bbox_intersects(route_bbox, line_bbox(line), pad_deg):
            continue
        if line_distance_m(route_lonlat, line) <= threshold_m:
            crossed.append(item)
    return {
        "crosses_flooded_road": bool(crossed),
        "affected_road_count": len(crossed),
        "max_depth_m": max((item.depth_m for item in crossed), default=0),
        "max_depth_cm": max((item.depth_cm for item in crossed), default=0),
        "max_factor": max((item.factor for item in crossed), default=0),
        "roads": crossed,
    }


def select_features_near_route(
    route_lonlat: list[tuple[float, float]],
    flood_features: list[FloodFeature],
    threshold_m: float = 30.0,
    max_count: int = 80,
) -> list[FloodFeature]:
    scored: list[tuple[float, FloodFeature]] = []
    if len(route_lonlat) < 2:
        return []
    route_bbox = line_bbox(route_lonlat)
    pad_deg = threshold_m / 111_320.0
    for item in flood_features:
        line = [(float(lon), float(lat)) for lon, lat in item.geometry.get("coordinates", [])]
        if len(line) < 2 or not bbox_intersects(route_bbox, line_bbox(line), pad_deg):
            continue
        dist = line_distance_m(route_lonlat, line)
        if dist <= threshold_m:
            scored.append((dist, item))
    scored.sort(key=lambda pair: (pair[0], -pair[1].factor, -pair[1].depth_cm))
    return [item for _, item in scored[:max_count]]


def top_deepest_features(flood_features: list[FloodFeature], max_count: int = 80) -> list[FloodFeature]:
    return sorted(flood_features, key=lambda item: (-item.depth_cm, -item.factor))[:max_count]
