#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from flood_utils import (
    DATA_FILE,
    REQUESTS_DIR,
    build_flood_features,
    load_geojson,
    route_request,
    save_json,
    to_linear_cost_factor_feature,
    top_deepest_features,
)


def time_slug(time_step: str) -> str:
    return "T" + time_step.split("T", 1)[1].split(":", 1)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Valhalla linear_cost_factors from flood-road GeoJSON.")
    parser.add_argument("--file", default=str(DATA_FILE))
    parser.add_argument("--time", default="2026-05-22T18:00:00")
    parser.add_argument("--vehicle", default="motorbike")
    parser.add_argument("--costing", default="motor_scooter")
    parser.add_argument("--max-count", type=int, default=80)
    parser.add_argument("--selection", choices=["top-deepest", "all"], default="top-deepest")
    parser.add_argument("--output")
    parser.add_argument("--route-output")
    args = parser.parse_args()

    data = load_geojson(Path(args.file))
    flood_features = build_flood_features(data, args.time, args.vehicle)
    selected = flood_features if args.selection == "all" else top_deepest_features(flood_features, args.max_count)
    linear = [to_linear_cost_factor_feature(item) for item in selected]

    slug = time_slug(args.time)
    output = Path(args.output) if args.output else REQUESTS_DIR / f"linear_cost_factors_{slug}_{args.vehicle}.json"
    save_json(output, {"type": "FeatureCollection", "features": linear})

    route_output = (
        Path(args.route_output)
        if args.route_output
        else REQUESTS_DIR / f"flood_aware_{slug}_{args.vehicle}.json"
    )
    save_json(route_output, route_request(costing=args.costing, linear_cost_factors=linear))

    print(f"Wrote {output}")
    print(f"Wrote {route_output}")
    print(f"Candidate flooded features factor>1: {len(flood_features)}")
    print(f"Selected features: {len(selected)}")
    print(f"Max factor: {max((item.factor for item in selected), default=0)}")
    print(f"Max depth cm: {max((item.depth_cm for item in selected), default=0):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
