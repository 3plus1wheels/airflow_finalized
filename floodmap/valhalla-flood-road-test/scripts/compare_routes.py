#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from flood_utils import (
    DATA_FILE,
    RESPONSES_DIR,
    build_flood_features,
    decode_polyline,
    flood_exposure,
    load_geojson,
    route_summary,
)


def load_response(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def same_shape(a: str | None, b: str | None) -> bool:
    return bool(a and b and a == b)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare baseline, flood-aware, and negative-control responses.")
    parser.add_argument("--time", default="2026-05-22T18:00:00")
    parser.add_argument("--vehicle", default="motorbike")
    parser.add_argument("--threshold-m", type=float, default=12)
    args = parser.parse_args()

    baseline = route_summary(load_response(RESPONSES_DIR / "baseline.json"))
    flood = route_summary(load_response(RESPONSES_DIR / "flood_aware_T18_motorbike.json"))
    negative = route_summary(load_response(RESPONSES_DIR / "negative_control.json"))
    flood_features = build_flood_features(load_geojson(DATA_FILE), args.time, args.vehicle)

    if not baseline.get("ok") or not flood.get("ok"):
        print("Route Test Result: FAIL")
        print(f"Baseline ok: {baseline.get('ok')} error={baseline.get('error')}")
        print(f"Flood-aware ok: {flood.get('ok')} error={flood.get('error')}")
        return 2

    baseline_exposure = flood_exposure(decode_polyline(baseline.get("shape")), flood_features, args.threshold_m)
    flood_exposure_result = flood_exposure(decode_polyline(flood.get("shape")), flood_features, args.threshold_m)

    route_changed = not same_shape(baseline.get("shape"), flood.get("shape"))
    negative_changed = not same_shape(baseline.get("shape"), negative.get("shape"))
    exposure_reduced = flood_exposure_result["max_depth_cm"] < baseline_exposure["max_depth_cm"] or (
        flood_exposure_result["affected_road_count"] < baseline_exposure["affected_road_count"]
    )

    if route_changed and exposure_reduced and not negative_changed:
        result = "PASS"
    elif not baseline_exposure["crosses_flooded_road"]:
        result = "INCONCLUSIVE"
    elif negative_changed:
        result = "INCONCLUSIVE"
    else:
        result = "INCONCLUSIVE"

    print(f"Route Test Result: {result}")
    print("")
    print("Baseline:")
    print(f"- Distance: {baseline.get('distance_km')} km")
    print(f"- Duration: {baseline.get('duration_min')} min")
    print(f"- Crosses flooded roads: {baseline_exposure['crosses_flooded_road']}")
    print(f"- Affected roads: {baseline_exposure['affected_road_count']}")
    print(f"- Max crossed depth: {baseline_exposure['max_depth_cm']:.1f} cm")
    print("")
    print("Flood-aware:")
    print(f"- Distance: {flood.get('distance_km')} km")
    print(f"- Duration: {flood.get('duration_min')} min")
    print(f"- Crosses flooded roads: {flood_exposure_result['crosses_flooded_road']}")
    print(f"- Affected roads: {flood_exposure_result['affected_road_count']}")
    print(f"- Max crossed depth: {flood_exposure_result['max_depth_cm']:.1f} cm")
    print("")
    print("Negative control:")
    print(f"- Route changed: {negative_changed}")
    print("")
    print("Decision:")
    if result == "PASS":
        print("Recommend flood-aware route.")
    else:
        print("Need inspect selected route, Valhalla edge matching, or alternative path availability.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
