#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
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
    to_flood_polygon_feature,
    to_linear_cost_factor_feature,
    top_deepest_features,
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
        hard_exclusions = self._hard_exclusions(selected)
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
        costing = "motor_scooter" if vehicle_type == "motorbike" else body.get("costing", "auto")

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
        hard_exclusions = self._hard_exclusions(selected)
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
            bbox = bbox_for_geojson(ADAPTER.geojson)
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
            vehicle = qs.get("vehicle_type", ["motorbike"])[0]
            self._send(200, ADAPTER.roads(time_step, vehicle))
        elif parsed.path == "/flood/polygons":
            require_features = qs.get("mode", ["latest"])[0] in {"nonempty", "rain"}
            ADAPTER.refresh_geojson(force=True, require_features=require_features)
            steps = available_timesteps(ADAPTER.geojson)
            time_step = qs.get("time", [steps[-1] if steps else ""])[0]
            vehicle = qs.get("vehicle_type", ["motorbike"])[0]
            self._send(200, ADAPTER.polygons(time_step, vehicle))
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
