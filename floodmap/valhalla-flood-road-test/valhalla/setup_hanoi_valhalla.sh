#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/source"
CUSTOM_DIR="${SCRIPT_DIR}/custom_files"

VIETNAM_URL="https://download.geofabrik.de/asia/vietnam-latest.osm.pbf"
VIETNAM_PBF="${SOURCE_DIR}/vietnam-latest.osm.pbf"
HANOI_PBF="${CUSTOM_DIR}/hanoi.osm.pbf"

# Hanoi metro bbox: west,south,east,north.
# Wide enough for current flood test points and nearby detours.
HANOI_BBOX="105.25,20.55,106.10,21.40"

mkdir -p "${SOURCE_DIR}" "${CUSTOM_DIR}"

if [[ ! -f "${VIETNAM_PBF}" ]]; then
  echo "Downloading Vietnam OSM extract from Geofabrik..."
  curl --fail --location --continue-at - \
    --output "${VIETNAM_PBF}" \
    "${VIETNAM_URL}"
else
  echo "Using existing ${VIETNAM_PBF}"
fi

if [[ ! -f "${HANOI_PBF}" ]]; then
  echo "Extracting Hanoi bbox ${HANOI_BBOX}..."
  docker run --rm \
    -v "${SCRIPT_DIR}:/work" \
    -w /work \
    mschilde/osmium-tool \
    osmium extract \
      --bbox="${HANOI_BBOX}" \
      --strategy=smart \
      --overwrite \
      --output "custom_files/hanoi.osm.pbf" \
      "source/vietnam-latest.osm.pbf"
else
  echo "Using existing ${HANOI_PBF}"
fi

echo "Starting Valhalla..."
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" up -d

echo "Valhalla container started. First boot may build graph tiles before API is ready."
echo "Logs: docker compose -f ${SCRIPT_DIR}/docker-compose.yml logs -f valhalla"
