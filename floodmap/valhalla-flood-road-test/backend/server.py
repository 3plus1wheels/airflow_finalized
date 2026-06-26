#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    import boto3
    from botocore.config import Config
except ImportError:
    boto3 = None
    Config = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

MAX_ROUTE_CONSTRAINTS = int(os.environ.get("FLOOD_MAX_ROUTE_CONSTRAINTS", "4"))
MAX_EXCLUDE_LOCATIONS = int(os.environ.get("FLOOD_MAX_EXCLUDE_LOCATIONS", "35"))
USE_HARD_EXCLUDES = os.environ.get("FLOOD_USE_HARD_EXCLUDES", "false").lower() == "true"
PROBE_EDGE_WALKABLE = os.environ.get("FLOOD_PROBE_EDGE_WALKABLE", "false").lower() == "true"

from flood_utils import (  # noqa: E402
    DATA_FILE,
    DEFAULT_COSTING,
    DEFAULT_DESTINATION,
    DEFAULT_ORIGIN,
    available_timesteps,
    bbox_for_geojson,
    build_flood_features,
    dangerous_flood_features,
    decode_polyline,
    exclude_locations_from_features,
    flood_exposure,
    load_geojson,
    post_valhalla_route,
    route_request,
    route_summary,
    select_features_near_route,
    segment_distance_m,
    to_flood_polygon_feature,
    to_linear_cost_factor_feature,
    top_deepest_features,
    vehicle_costing,
    vehicle_profile,
    vehicle_threshold_cm,
    vehicle_types,
)


class FloodConstraintAdapter:
    def __init__(self, valhalla_url: str = "http://localhost:8002") -> None:
        self.valhalla_url = valhalla_url
        self.geojson_source = ""
        self.geojson_source_last_modified = ""
        self.geojson_loaded_at = ""
        self.geojson = {}
        self._last_refresh = 0.0
        self._refresh_interval = int(os.environ.get("FLOOD_REFRESH_SECONDS", "30"))
        self.refresh_geojson(force=True)

    def refresh_geojson(self, force: bool = False, require_features: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_refresh < self._refresh_interval:
            return
        self._last_refresh = now
        try:
            geojson, source, last_modified = self._load_latest_minio_geojson(require_features=require_features)
        except Exception as exc:
            print(f"MinIO flood GeoJSON load skipped: {exc}")
            if require_features:
                geojson = {"type": "FeatureCollection", "features": []}
                source = f"no non-empty MinIO flood GeoJSON ({exc})"
                last_modified = ""
            else:
                geojson, source, last_modified = self._load_fallback_geojson()
        self.geojson = geojson
        self.geojson_source = source
        self.geojson_source_last_modified = last_modified
        self.geojson_loaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _load_latest_minio_geojson(self, require_features: bool = False) -> tuple[dict, str, str]:
        bucket = os.environ.get("FLOOD_MINIO_BUCKET")
        endpoint = os.environ.get("FLOOD_MINIO_ENDPOINT")
        access_key = os.environ.get("FLOOD_MINIO_ACCESS_KEY")
        secret_key = os.environ.get("FLOOD_MINIO_SECRET_KEY")
        prefix = os.environ.get("FLOOD_MINIO_PREFIX", "")
        if not all([bucket, endpoint, access_key, secret_key]):
            raise RuntimeError("FLOOD_MINIO_* settings are incomplete")
        if boto3 is None or Config is None:
            raise RuntimeError("boto3 is not installed")

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4"),
        )
        paginator = client.get_paginator("list_objects_v2")
        candidates = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item.get("Key", "")
                name = Path(key).name
                if name.startswith("flood_road_") and name.endswith(".geojson") and "/" in key:
                    candidates.append(item)
        if not candidates:
            raise RuntimeError(f"no timestamped flood_road_*.geojson objects found in s3://{bucket}/{prefix}")

        for latest in sorted(candidates, key=lambda item: item["LastModified"], reverse=True):
            key = latest["Key"]
            response = client.get_object(Bucket=bucket, Key=key)
            body = response["Body"].read().decode("utf-8")
            geojson = json.loads(body)
            if require_features and not geojson.get("features"):
                print(f"Skipping empty flood GeoJSON for rain mode: s3://{bucket}/{key}")
                continue
            source = f"s3://{bucket}/{key}"
            modified = latest["LastModified"].isoformat()
            mode = "latest non-empty" if require_features else "latest"
            print(f"Loaded {mode} flood GeoJSON from {source}")
            return geojson, source, modified

        raise RuntimeError(f"no non-empty flood_road_*.geojson objects found in s3://{bucket}/{prefix}")

    def _load_fallback_geojson(self) -> tuple[dict, str, str]:
        fallback = os.environ.get("FLOOD_LOCAL_FALLBACK", str(DATA_FILE))
        path = Path(fallback)
        if not path.is_absolute():
            path = ROOT / path
        print(f"Loaded fallback flood GeoJSON from {path}")
        return load_geojson(path), str(path), ""

    def timesteps(self) -> list[str]:
        self.refresh_geojson()
        return available_timesteps(self.geojson)

    def latest_timestep(self) -> str:
        steps = self.timesteps()
        if not steps:
            raise ValueError("no flood timesteps found")
        return steps[-1]

    def roads(self, time_step: str, vehicle_type: str = "motorbike") -> dict:
        self.refresh_geojson()
        if not time_step:
            return {"type": "FeatureCollection", "features": []}
        features = build_flood_features(self.geojson, time_step, vehicle_type, include_factor_one=True)
        return {
            "type": "FeatureCollection",
            "features": [to_linear_cost_factor_feature(item) for item in features],
        }

    def polygons(self, time_step: str, vehicle_type: str = "motorbike") -> dict:
        self.refresh_geojson()
        if not time_step:
            return {"type": "FeatureCollection", "features": []}
        features = build_flood_features(self.geojson, time_step, vehicle_type, include_factor_one=True)
        return {
            "type": "FeatureCollection",
            "features": [to_flood_polygon_feature(item) for item in features],
        }

    def route_forecast(
        self,
        origin: dict,
        destination: dict,
        departure_time: str = "",
        mode: str = "latest",
        alternates: int = 2,
        force_refresh: bool = False,
    ) -> dict:
        require_features = mode in {"nonempty", "rain"}
        has_features = bool(self.geojson.get("features"))
        self.refresh_geojson(force=force_refresh or (require_features and not has_features), require_features=require_features)
        steps = available_timesteps(self.geojson)
        departure_dt = self._parse_departure_time(departure_time)
        fallback_step = steps[-1] if steps else ""

        vehicles = {}
        routes_by_vehicle = {}
        forecast_by_vehicle = {}
        best_departure = {}
        visible_windows = self._window_starts(departure_dt, 8)
        scan_windows = self._window_starts(departure_dt, 12)

        for vehicle_type in vehicle_types():
            profile = vehicle_profile(vehicle_type)
            threshold_cm = vehicle_threshold_cm(vehicle_type)
            routes = self._vehicle_route_candidates(
                origin,
                destination,
                vehicle_type,
                departure_dt,
                steps,
                max(0, min(int(alternates), 2)),
            )
            routes_by_vehicle[vehicle_type] = routes
            selected = routes[0] if routes else None
            coords = decode_polyline(route_summary(selected["route"]).get("shape")) if selected else []
            scan = self._route_depth_forecast(coords, vehicle_type, scan_windows, steps)
            forecast = scan[: len(visible_windows)]
            forecast_by_vehicle[vehicle_type] = forecast
            best_departure[vehicle_type] = self._best_departure(scan, threshold_cm)
            vehicles[vehicle_type] = {
                "id": vehicle_type,
                "label_vi": profile["label_vi"],
                "label_en": profile["label_en"],
                "costing": profile["costing"],
                "threshold_cm": threshold_cm,
                "eta_min": selected.get("duration_min") if selected else None,
                "distance_km": selected.get("distance_km") if selected else None,
                "selected_route_id": selected.get("id") if selected else "",
                "route_count": len(routes),
                "error": "" if selected else "No route returned",
            }

        return {
            "origin": origin,
            "destination": destination,
            "departure_time": self._format_iso(departure_dt),
            "visible_window_hours": 4,
            "scan_window_hours": 6,
            "bar_minutes": 30,
            "timestep_minutes": 15,
            "thresholds_cm": {vehicle: vehicle_threshold_cm(vehicle) for vehicle in vehicle_types()},
            "vehicles": vehicles,
            "routes_by_vehicle": routes_by_vehicle,
            "forecast_by_vehicle": forecast_by_vehicle,
            "best_departure": best_departure,
            "flood_time_step": fallback_step,
            "available_timesteps": steps,
            "latest_timestep": steps[-1] if steps else None,
            "is_stale": any(
                bar.get("stale")
                for vehicle_forecast in forecast_by_vehicle.values()
                for bar in vehicle_forecast
            ),
            "flood_geojson_source": self.geojson_source,
            "flood_geojson_last_modified": self.geojson_source_last_modified,
            "flood_geojson_loaded_at": self.geojson_loaded_at,
        }

    def _vehicle_route_candidates(
        self,
        origin: dict,
        destination: dict,
        vehicle_type: str,
        departure_dt: datetime,
        steps: list[str],
        alternates: int,
    ) -> list[dict]:
        costing = vehicle_costing(vehicle_type)
        departure_step, _ = self._step_for_datetime(steps, departure_dt)
        route_responses = []
        baseline_request = route_request(origin, destination, costing, alternates=alternates)
        baseline_response = post_valhalla_route(baseline_request, self.valhalla_url, timeout=12)
        route_responses.extend((item, "fastest") for item in self._extract_route_responses(baseline_response))

        baseline_summary = route_summary(baseline_response)
        if baseline_summary.get("ok"):
            route_responses.extend(
                (item, "alternate")
                for item in self._route_exclusion_variants(
                    origin,
                    destination,
                    costing,
                    decode_polyline(baseline_summary.get("shape")),
                    alternates,
                )
            )
        depth_features = build_flood_features(
            self.geojson,
            departure_step,
            vehicle_type,
            include_factor_one=True,
        ) if departure_step else []
        routes = []
        seen_shapes = set()
        for response, source in route_responses:
            summary = route_summary(response)
            shape = summary.get("shape")
            shape_key = json.dumps(shape, sort_keys=True) if isinstance(shape, dict) else str(shape or "")
            if not summary.get("ok") or not shape_key or shape_key in seen_shapes:
                continue
            seen_shapes.add(shape_key)
            route_lonlat = decode_polyline(shape)
            if depth_features:
                self._annotate_maneuver_depths(response, route_lonlat, depth_features)
            exposure = self._flood_exposure_fast(route_lonlat, depth_features) if depth_features else {}
            routes.append(
                {
                    "id": "",
                    "source": source,
                    "label_vi": self._route_label_vi(source),
                    "label_en": self._route_label_en(source),
                    "distance_km": summary.get("distance_km"),
                    "duration_min": summary.get("duration_min"),
                    "max_depth_cm": round(exposure.get("max_depth_cm", 0), 1),
                    "affected_road_count": exposure.get("affected_road_count", 0),
                    "crosses_threshold": exposure.get("max_depth_cm", 0) >= vehicle_threshold_cm(vehicle_type),
                    "route": response,
                }
            )

        routes.sort(
            key=lambda item: (
                item["max_depth_cm"],
                item["duration_min"] if item["duration_min"] is not None else float("inf"),
                item["distance_km"] if item["distance_km"] is not None else float("inf"),
            )
        )
        for index, item in enumerate(routes[:3], start=1):
            item["id"] = f"{vehicle_type}-route-{index}"
            if index == 1:
                item["label_vi"] = "Đề xuất"
                item["label_en"] = "Recommended"
        return routes[:3]

    def _annotate_maneuver_depths(
        self,
        route_response: dict,
        route_lonlat: list[tuple[float, float]],
        flood_features: list,
    ) -> None:
        legs = route_response.get("json", {}).get("trip", {}).get("legs", [])
        for leg in legs:
            maneuvers = leg.get("maneuvers", [])
            for maneuver in maneuvers:
                begin = int(maneuver.get("begin_shape_index", 0) or 0)
                end = int(maneuver.get("end_shape_index", begin) or begin)
                begin = max(0, min(begin, len(route_lonlat) - 1))
                end = max(begin, min(end, len(route_lonlat) - 1))
                section = route_lonlat[begin : end + 1]
                if len(section) < 2 and begin > 0:
                    section = route_lonlat[begin - 1 : end + 1]
                exposure = self._flood_exposure_fast(section, flood_features) if len(section) >= 2 else {}
                depth_cm = float(exposure.get("max_depth_cm", 0) or 0)
                maneuver["max_depth_cm"] = round(depth_cm, 1)
                maneuver["flooded"] = depth_cm > 0
                maneuver["affected_road_count"] = int(exposure.get("affected_road_count", 0) or 0)

    def _route_exclusion_variants(
        self,
        origin: dict,
        destination: dict,
        costing: str,
        route_lonlat: list[tuple[float, float]],
        max_variants: int,
    ) -> list[dict]:
        if len(route_lonlat) < 5:
            return []
        variants = []
        for ratio in (0.33, 0.66)[: max(0, min(max_variants, 2))]:
            lon, lat = route_lonlat[max(1, min(len(route_lonlat) - 2, int((len(route_lonlat) - 1) * ratio)))]
            request = route_request(
                origin,
                destination,
                costing,
                exclude_locations=[{"lat": lat, "lon": lon}],
            )
            response = post_valhalla_route(request, self.valhalla_url, timeout=3)
            variants.extend(self._extract_route_responses(response))
        return variants

    def _route_label_vi(self, source: str) -> str:
        if source == "safer":
            return "Ít ngập hơn"
        if source == "alternate":
            return "Tuyến khác"
        return "Nhanh nhất"

    def _route_label_en(self, source: str) -> str:
        if source == "safer":
            return "Less flooded"
        if source == "alternate":
            return "Alternative"
        return "Fastest"

    def _flood_exposure_fast(
        self,
        route_lonlat: list[tuple[float, float]],
        flood_features: list,
        threshold_m: float = 12.0,
    ) -> dict:
        crossed = []
        if len(route_lonlat) < 2:
            return {
                "crosses_flooded_road": False,
                "affected_road_count": 0,
                "max_depth_m": 0,
                "max_depth_cm": 0,
                "max_factor": 0,
                "roads": crossed,
            }

        route_bbox = self._line_bbox(route_lonlat)
        pad_deg = threshold_m / 111_320.0
        for item in flood_features:
            coords = [(float(lon), float(lat)) for lon, lat in item.geometry.get("coordinates", [])]
            if len(coords) < 2:
                continue
            if self._bbox_intersects(route_bbox, self._line_bbox(coords), pad_deg):
                if self._line_within_threshold_m(route_lonlat, coords, threshold_m):
                    crossed.append(item)

        return {
            "crosses_flooded_road": bool(crossed),
            "affected_road_count": len(crossed),
            "max_depth_m": max((item.depth_m for item in crossed), default=0),
            "max_depth_cm": max((item.depth_cm for item in crossed), default=0),
            "max_factor": max((item.factor for item in crossed), default=0),
            "roads": crossed,
        }

    def _line_within_threshold_m(
        self,
        line_a: list[tuple[float, float]],
        line_b: list[tuple[float, float]],
        threshold_m: float,
    ) -> bool:
        if len(line_a) < 2 or len(line_b) < 2:
            return False
        pad_deg = threshold_m / 111_320.0
        for i in range(len(line_a) - 1):
            a1 = line_a[i]
            a2 = line_a[i + 1]
            a_bbox = self._segment_bbox(a1, a2)
            for j in range(len(line_b) - 1):
                b1 = line_b[j]
                b2 = line_b[j + 1]
                if not self._bbox_intersects(a_bbox, self._segment_bbox(b1, b2), pad_deg):
                    continue
                if segment_distance_m(a1, a2, b1, b2) <= threshold_m:
                    return True
        return False

    def _segment_bbox(
        self,
        a: tuple[float, float],
        b: tuple[float, float],
    ) -> tuple[float, float, float, float]:
        return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])

    def _line_bbox(self, line: list[tuple[float, float]]) -> tuple[float, float, float, float]:
        lons = [point[0] for point in line]
        lats = [point[1] for point in line]
        return min(lons), min(lats), max(lons), max(lats)

    def _bbox_intersects(
        self,
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

    def _extract_route_responses(self, response: dict) -> list[dict]:
        if not response.get("ok"):
            return []
        root = response.get("json", {})
        extracted = []

        def add_trip(trip: dict | None) -> None:
            if not isinstance(trip, dict) or not trip.get("legs"):
                return
            extracted.append(
                {
                    "ok": True,
                    "status": response.get("status"),
                    "json": {
                        "trip": trip,
                        "units": root.get("units", "kilometers"),
                        "language": root.get("language", "en-US"),
                    },
                }
            )

        add_trip(root.get("trip"))
        for item in root.get("alternates", []) or []:
            add_trip(item.get("trip") if isinstance(item, dict) else None)
            if isinstance(item, dict):
                add_trip(item)
        for item in root.get("alternate_paths", []) or []:
            add_trip(item.get("trip") if isinstance(item, dict) else None)
            if isinstance(item, dict):
                add_trip(item)
        for item in root.get("trip", {}).get("alternates", []) or []:
            add_trip(item.get("trip") if isinstance(item, dict) else None)
            if isinstance(item, dict):
                add_trip(item)
        return extracted

    def _route_depth_forecast(
        self,
        route_lonlat: list[tuple[float, float]],
        vehicle_type: str,
        windows: list[datetime],
        steps: list[str],
    ) -> list[dict]:
        forecast = []
        feature_cache = {}
        exposure_cache = {}
        for index, start in enumerate(windows):
            end = start + timedelta(minutes=30)
            depth_cm = 0.0
            source_steps = []
            stale = False
            for offset in (0, 15):
                step, step_stale = self._step_for_datetime(steps, start + timedelta(minutes=offset))
                if step:
                    source_steps.append(step)
                    if step not in feature_cache:
                        feature_cache[step] = build_flood_features(
                            self.geojson,
                            step,
                            vehicle_type,
                            include_factor_one=True,
                        )
                    if step not in exposure_cache:
                        features = feature_cache[step]
                        exposure_cache[step] = self._flood_exposure_fast(route_lonlat, features) if route_lonlat else {}
                    exposure = exposure_cache[step]
                    depth_cm = max(depth_cm, float(exposure.get("max_depth_cm", 0)))
                stale = stale or step_stale
            forecast.append(
                {
                    "index": index,
                    "starts_at": self._format_iso(start),
                    "ends_at": self._format_iso(end),
                    "label": self._format_clock(start),
                    "depth_cm": round(depth_cm, 1),
                    "severity": self._severity(depth_cm),
                    "safe": depth_cm < vehicle_threshold_cm(vehicle_type),
                    "is_now": index == 0,
                    "source_timesteps": source_steps,
                    "stale": stale,
                }
            )
        return forecast

    def _best_departure(self, scan: list[dict], threshold_cm: float) -> dict:
        for index, window in enumerate(scan):
            if window.get("depth_cm", 0) < threshold_cm:
                if index == 0:
                    return {
                        "status": "go_now",
                        "time": window["starts_at"],
                        "outside_visible": False,
                        "label_vi": "đi ngay",
                        "label_en": "go now",
                    }
                clock = self._format_clock(self._parse_departure_time(window["starts_at"]))
                return {
                    "status": "wait_until",
                    "time": window["starts_at"],
                    "outside_visible": index >= 8,
                    "label_vi": f"đợi đến {clock}",
                    "label_en": f"wait until {clock}",
                }
        return {
            "status": "none",
            "time": "",
            "outside_visible": True,
            "label_vi": "không có khung giờ an toàn trong 6h tới",
            "label_en": "no safe 30-min window in next 6h",
        }

    def _parse_departure_time(self, value: str = "") -> datetime:
        if value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None, second=0, microsecond=0)
            except ValueError:
                pass
        return datetime.now().replace(second=0, microsecond=0)

    def _window_starts(self, departure_dt: datetime, count: int) -> list[datetime]:
        return [departure_dt + timedelta(minutes=30 * index) for index in range(count)]

    def _step_for_datetime(self, steps: list[str], value: datetime) -> tuple[str, bool]:
        if not steps:
            return "", True
        candidates = [
            self._format_iso(value),
            value.strftime("%Y-%m-%dT%H:%M"),
            value.isoformat(),
        ]
        for candidate in candidates:
            if candidate in steps:
                return candidate, False
        return steps[-1], True

    def _format_iso(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%S")

    def _format_clock(self, value: datetime) -> str:
        return value.strftime("%I:%M %p").lstrip("0")

    def _severity(self, depth_cm: float) -> str:
        if depth_cm < 10:
            return "low"
        if depth_cm < 20:
            return "moderate"
        if depth_cm < 30:
            return "high"
        return "severe"

    def baseline(self, origin: dict, destination: dict, costing: str = DEFAULT_COSTING) -> dict:
        payload = route_request(origin, destination, costing)
        return post_valhalla_route(payload, self.valhalla_url)

    def _hard_exclusions(self, features: list, min_depth_m: float = 0.20) -> dict:
        blocked_features = dangerous_flood_features(features, min_depth_m)
        locations = exclude_locations_from_features(blocked_features, max_points_per_feature=1)[:MAX_EXCLUDE_LOCATIONS]
        return {
            "min_depth_m": min_depth_m,
            "count": len(locations),
            "feature_count": len(blocked_features),
            "locations": locations,
        }

    def flood_aware(
        self,
        origin: dict,
        destination: dict,
        flood_time_step: str,
        vehicle_type: str = "motorbike",
        costing: str = DEFAULT_COSTING,
        require_features: bool = False,
    ) -> dict:
        self.refresh_geojson(force=True, require_features=require_features)
        if costing == DEFAULT_COSTING and vehicle_type != "motorbike":
            costing = vehicle_costing(vehicle_type)
        baseline = self.baseline(origin, destination, costing)
        summary = route_summary(baseline)
        if not flood_time_step:
            flood_time_step = ""
        all_flood = build_flood_features(self.geojson, flood_time_step, vehicle_type) if flood_time_step else []
        selected = top_deepest_features(all_flood, MAX_ROUTE_CONSTRAINTS)
        if summary.get("ok"):
            route_shape = decode_polyline(summary.get("shape"))
            near = select_features_near_route(route_shape, all_flood, threshold_m=30, max_count=MAX_ROUTE_CONSTRAINTS)
            if near:
                selected = near
        selected = self._edge_walkable(selected, costing)
        linear = [to_linear_cost_factor_feature(item) for item in selected]
        hard_exclusions = self._hard_exclusions(selected, vehicle_threshold_cm(vehicle_type) / 100)
        request = route_request(
            origin,
            destination,
            costing,
            linear,
            exclude_locations=hard_exclusions["locations"] if USE_HARD_EXCLUDES else None,
        )
        response = self._post_constrained_route(request, origin, destination, costing, selected)
        response["linear_cost_factors"] = {
            "count": len(linear),
            "max_factor": max((item.factor for item in selected), default=0),
            "max_depth_m": max((item.depth_m for item in selected), default=0),
            "max_depth_cm": max((item.depth_cm for item in selected), default=0),
        }
        response["hard_exclusions"] = hard_exclusions
        return response

    def compare(self, body: dict) -> dict:
        require_features = body.get("flood_source_mode") in {"nonempty", "rain"}
        self.refresh_geojson(force=True, require_features=require_features)
        origin = body["origin"]
        destination = body["destination"]
        vehicle_type = body.get("vehicle_type", "motorbike")
        steps = available_timesteps(self.geojson)
        flood_time_step = body.get("flood_time_step") or (steps[-1] if steps else "")
        costing = body.get("costing") or vehicle_costing(vehicle_type)

        baseline_response = self.baseline(origin, destination, costing)
        baseline = route_summary(baseline_response)
        all_flood = build_flood_features(self.geojson, flood_time_step, vehicle_type) if flood_time_step else []
        selected = top_deepest_features(all_flood, MAX_ROUTE_CONSTRAINTS)

        if baseline.get("ok"):
            selected_near = select_features_near_route(
                decode_polyline(baseline.get("shape")), all_flood, threshold_m=30, max_count=MAX_ROUTE_CONSTRAINTS
            )
            if selected_near:
                selected = selected_near

        selected = self._edge_walkable(selected, costing)
        linear = [to_linear_cost_factor_feature(item) for item in selected]
        hard_exclusions = self._hard_exclusions(selected, vehicle_threshold_cm(vehicle_type) / 100)
        flood_request = route_request(
            origin,
            destination,
            costing,
            linear,
            exclude_locations=hard_exclusions["locations"] if USE_HARD_EXCLUDES else None,
        )
        flood_response = self._post_constrained_route(
            flood_request,
            origin,
            destination,
            costing,
            selected,
        )
        flood = route_summary(flood_response)

        baseline_exp = (
            flood_exposure(decode_polyline(baseline.get("shape")), all_flood) if baseline.get("ok") else {}
        )
        flood_exp = flood_exposure(decode_polyline(flood.get("shape")), all_flood) if flood.get("ok") else {}

        route_changed = baseline.get("shape") != flood.get("shape") if baseline.get("ok") and flood.get("ok") else False
        exposure_reduced = (flood_exp.get("max_depth_cm", 0) < baseline_exp.get("max_depth_cm", 0)) or (
            flood_exp.get("affected_road_count", 0) < baseline_exp.get("affected_road_count", 0)
        )
        result = "PASS" if route_changed and exposure_reduced else "INCONCLUSIVE"
        if not baseline_response.get("ok") or not flood_response.get("ok"):
            result = "FAIL"

        return {
            "result": result,
            "vehicle_type": vehicle_type,
            "flood_time_step": flood_time_step,
            "baseline": {
                "distance_km": baseline.get("distance_km"),
                "duration_min": baseline.get("duration_min"),
                "crosses_flooded_road": baseline_exp.get("crosses_flooded_road", False),
                "max_depth_m": baseline_exp.get("max_depth_m", 0),
                "max_depth_cm": baseline_exp.get("max_depth_cm", 0),
                "affected_road_count": baseline_exp.get("affected_road_count", 0),
                "route": baseline_response,
            },
            "flood_aware": {
                "distance_km": flood.get("distance_km"),
                "duration_min": flood.get("duration_min"),
                "crosses_flooded_road": flood_exp.get("crosses_flooded_road", False),
                "max_depth_m": flood_exp.get("max_depth_m", 0),
                "max_depth_cm": flood_exp.get("max_depth_cm", 0),
                "affected_road_count": flood_exp.get("affected_road_count", 0),
                "route": flood_response,
            },
            "linear_cost_factors": {
                "count": len(linear),
                "max_factor": max((item.factor for item in selected), default=0),
                "max_depth_m": max((item.depth_m for item in selected), default=0),
                "features": linear,
            },
            "hard_exclusions": hard_exclusions,
            "decision": "Recommend flood-aware route." if result == "PASS" else "Review result before using.",
            "reason": "Baseline route crosses road segments with unsafe flood depth."
            if baseline_exp.get("crosses_flooded_road")
            else "Baseline did not clearly cross selected flooded roads.",
        }

    def _edge_walkable(self, features: list, costing: str) -> list:
        if not PROBE_EDGE_WALKABLE:
            return features[:MAX_ROUTE_CONSTRAINTS]
        kept = []
        for item in features[:MAX_ROUTE_CONSTRAINTS]:
            probe = route_request(
                costing=costing,
                linear_cost_factors=[to_linear_cost_factor_feature(item)],
            )
            if post_valhalla_route(probe, self.valhalla_url).get("ok"):
                kept.append(item)
        return kept

    def _post_constrained_route(
        self,
        request: dict,
        origin: dict,
        destination: dict,
        costing: str,
        selected: list,
    ) -> dict:
        response = post_valhalla_route(request, self.valhalla_url)
        if response.get("ok"):
            return response

        tried = {len(selected)}
        size = len(selected) // 2
        while size > 0:
            if size not in tried:
                lighter = route_request(
                    origin,
                    destination,
                    costing,
                    [to_linear_cost_factor_feature(item) for item in selected[:size]],
                )
                retry = post_valhalla_route(lighter, self.valhalla_url)
                if retry.get("ok"):
                    retry["constraint_warning"] = response.get("error", "full constraint route failed")
                    retry["constraint_count_used"] = size
                    return retry
                tried.add(size)
            size //= 2

        fallback = post_valhalla_route(route_request(origin, destination, costing), self.valhalla_url)
        if fallback.get("ok"):
            fallback["constraint_warning"] = response.get("error", "all constrained route attempts failed")
            fallback["constraint_count_used"] = 0
            return fallback
        return response


ADAPTER = FloodConstraintAdapter(os.environ.get("VALHALLA_URL", "http://localhost:8002"))


def parse_latlon_param(value: str, fallback: dict) -> dict:
    if not value:
        return dict(fallback)
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2:
        raise ValueError(f"bad coordinate: {value}")
    lat = float(parts[0])
    lon = float(parts[1])
    return {"lat": lat, "lon": lon}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:
        self._send(204, {})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/health":
            ADAPTER.refresh_geojson()
            try:
                bbox = bbox_for_geojson(ADAPTER.geojson)
            except ValueError:
                bbox = None
            self._send(
                200,
                {
                    "ok": True,
                    "valhalla_url": ADAPTER.valhalla_url,
                    "bbox": bbox,
                    "flood_geojson_source": ADAPTER.geojson_source,
                    "flood_geojson_last_modified": ADAPTER.geojson_source_last_modified,
                    "flood_geojson_loaded_at": ADAPTER.geojson_loaded_at,
                },
            )
        elif parsed.path == "/flood/timesteps":
            require_features = qs.get("mode", ["latest"])[0] in {"nonempty", "rain"}
            ADAPTER.refresh_geojson(force=True, require_features=require_features)
            timesteps = available_timesteps(ADAPTER.geojson)
            self._send(
                200,
                {
                    "timesteps": timesteps,
                    "latest_timestep": timesteps[-1] if timesteps else None,
                    "flood_geojson_source": ADAPTER.geojson_source,
                    "flood_geojson_last_modified": ADAPTER.geojson_source_last_modified,
                    "flood_geojson_loaded_at": ADAPTER.geojson_loaded_at,
                },
            )
        elif parsed.path == "/flood/roads":
            require_features = qs.get("mode", ["latest"])[0] in {"nonempty", "rain"}
            ADAPTER.refresh_geojson(force=True, require_features=require_features)
            steps = available_timesteps(ADAPTER.geojson)
            time_step = qs.get("time", [steps[-1] if steps else ""])[0]
            if steps and time_step not in steps:
                time_step = steps[-1]
            vehicle = qs.get("vehicle_type", ["motorbike"])[0]
            self._send(200, ADAPTER.roads(time_step, vehicle))
        elif parsed.path == "/flood/polygons":
            require_features = qs.get("mode", ["latest"])[0] in {"nonempty", "rain"}
            ADAPTER.refresh_geojson(force=True, require_features=require_features)
            steps = available_timesteps(ADAPTER.geojson)
            time_step = qs.get("time", [steps[-1] if steps else ""])[0]
            if steps and time_step not in steps:
                time_step = steps[-1]
            vehicle = qs.get("vehicle_type", ["motorbike"])[0]
            self._send(200, ADAPTER.polygons(time_step, vehicle))
        elif parsed.path == "/flood/route/forecast":
            try:
                origin = parse_latlon_param(qs.get("origin", [""])[0], DEFAULT_ORIGIN)
                destination = parse_latlon_param(qs.get("destination", [""])[0], DEFAULT_DESTINATION)
                alternates = int(qs.get("alternates", ["2"])[0])
                self._send(
                    200,
                    ADAPTER.route_forecast(
                        origin,
                        destination,
                        qs.get("departure_time", [""])[0],
                        qs.get("mode", ["latest"])[0],
                        alternates,
                        qs.get("force", ["false"])[0].lower() in {"1", "true", "yes"},
                    ),
                )
            except Exception as exc:
                self._send(400, {"error": str(exc)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        try:
            if self.path == "/route/baseline":
                self._send(200, ADAPTER.baseline(body["origin"], body["destination"], body.get("costing", DEFAULT_COSTING)))
            elif self.path == "/route/flood-aware":
                require_features = body.get("flood_source_mode") in {"nonempty", "rain"}
                ADAPTER.refresh_geojson(force=True, require_features=require_features)
                steps = available_timesteps(ADAPTER.geojson)
                self._send(
                    200,
                    ADAPTER.flood_aware(
                        body["origin"],
                        body["destination"],
                        body.get("flood_time_step") or (steps[-1] if steps else ""),
                        body.get("vehicle_type", "motorbike"),
                        body.get("costing", DEFAULT_COSTING),
                        require_features,
                    ),
                )
            elif self.path == "/route/compare":
                self._send(200, ADAPTER.compare(body))
            else:
                self._send(404, {"error": "not found"})
        except Exception as exc:
            self._send(400, {"error": str(exc)})


def main() -> int:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8010"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Backend listening on http://{host}:{port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
