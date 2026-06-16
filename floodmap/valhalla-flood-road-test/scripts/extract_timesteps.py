#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from flood_utils import DATA_FILE, available_timesteps, load_geojson


def main() -> int:
    parser = argparse.ArgumentParser(description="Print flood GeoJSON time steps.")
    parser.add_argument("--file", default=str(DATA_FILE))
    args = parser.parse_args()

    for step in available_timesteps(load_geojson(Path(args.file))):
        print(step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
