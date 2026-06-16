#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from flood_utils import (
    DATA_FILE,
    REQUESTS_DIR,
    RESPONSES_DIR,
    build_flood_features,
    dangerous_flood_features,
    decode_polyline,
    exclude_locations_from_features,
    get_valhalla_status,
    load_geojson,
    post_valhalla_route,
    route_request,
    route_summary,
    save_json,
    select_features_near_route,
    to_linear_cost_factor_feature,
    top_deepest_features,
    version_tuple,
)


def keep_edge_walkable(features, costing, valhalla_url):
    kept = []
    rejected = []
    for item in features:
        probe = route_request(
            costing=costing,
            linear_cost_factors=[to_linear_cost_factor_feature(item)],
        )
        result = post_valhalla_route(probe, valhalla_url)
        if result.get("ok"):
            kept.append(item)
        else:
            rejected.append({"road_name": item.road_name, "depth_cm": item.depth_cm, "error": result.get("error")})
    return kept, rejected


def main() -> int:
    parser = argparse.ArgumentParser(description="Run baseline, flood-aware, and negative-control Valhalla tests.")
    parser.add_argument("--valhalla-url", default="http://localhost:8002")
    parser.add_argument("--time", default="2026-05-22T18:00:00")
    parser.add_argument("--vehicle", default="motorbike")
    parser.add_argument("--costing", default="motor_scooter")
    parser.add_argument("--near-threshold-m", type=float, default=30)
    parser.add_argument("--max-count", type=int, default=80)
    args = parser.parse_args()

    data = load_geojson(DATA_FILE)
    all_flood = build_flood_features(data, args.time, args.vehicle)
    status = get_valhalla_status(args.valhalla_url)
    if status.get("ok"):
        version = status.get("json", {}).get("version", "0.0.0")
        print(f"Valhalla version: {version}")
        if version_tuple(version) < (3, 6, 2):
            print("Warning: linear_cost_factors landed in Valhalla 3.6.2; older servers may ignore the field.")

    baseline_req = route_request(costing=args.costing)
    save_json(REQUESTS_DIR / "baseline.json", baseline_req)
    baseline_res = post_valhalla_route(baseline_req, args.valhalla_url)
    save_json(RESPONSES_DIR / "baseline.json", baseline_res)
    baseline_summary = route_summary(baseline_res)

    if not baseline_summary.get("ok"):
        print(f"Baseline failed: {baseline_summary.get('error')}")
        return 2

    baseline_shape = decode_polyline(baseline_summary.get("shape"))
    selected = select_features_near_route(
        baseline_shape, all_flood, threshold_m=args.near_threshold_m, max_count=args.max_count
    )
    if not selected:
        selected = top_deepest_features(all_flood, args.max_count)
    selected, rejected = keep_edge_walkable(selected, args.costing, args.valhalla_url)

    flood_linear = [to_linear_cost_factor_feature(item) for item in selected]
    hard_exclusions = exclude_locations_from_features(dangerous_flood_features(selected))
    flood_req = route_request(
        costing=args.costing,
        linear_cost_factors=flood_linear,
        exclude_locations=hard_exclusions,
    )
    save_json(REQUESTS_DIR / "flood_aware_T18_motorbike.json", flood_req)
    flood_res = post_valhalla_route(flood_req, args.valhalla_url)
    save_json(RESPONSES_DIR / "flood_aware_T18_motorbike.json", flood_res)

    negative_selected = top_deepest_features(
        [item for item in all_flood if item not in selected], args.max_count
    )
    negative_selected, negative_rejected = keep_edge_walkable(negative_selected, args.costing, args.valhalla_url)
    negative_req = route_request(
        costing=args.costing,
        linear_cost_factors=[to_linear_cost_factor_feature(item) for item in negative_selected],
    )
    save_json(REQUESTS_DIR / "negative_control.json", negative_req)
    negative_res = post_valhalla_route(negative_req, args.valhalla_url)
    save_json(RESPONSES_DIR / "negative_control.json", negative_res)

    print("Route test requests/responses written.")
    print(f"Baseline ok: {baseline_res.get('ok')}")
    print(f"Flood-aware ok: {flood_res.get('ok')}")
    print(f"Negative-control ok: {negative_res.get('ok')}")
    print(f"Selected flood factors: {len(flood_linear)}")
    print(f"Hard exclusion locations: {len(hard_exclusions)}")
    print(f"Rejected selected factors: {len(rejected)}")
    print(f"Rejected negative factors: {len(negative_rejected)}")
    print(f"Max factor: {max((item.factor for item in selected), default=0)}")
    print(f"Max depth cm: {max((item.depth_cm for item in selected), default=0):.1f}")
    return 0 if flood_res.get("ok") and negative_res.get("ok") else 3


if __name__ == "__main__":
    raise SystemExit(main())
