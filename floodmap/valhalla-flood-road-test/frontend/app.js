const API = window.FLOOD_API_BASE || "/api";

const map = L.map("map").setView([21.0219, 105.763], 16);
map.createPane("floodPolygonPane");
map.getPane("floodPolygonPane").style.zIndex = 430;
map.createPane("floodPane");
map.getPane("floodPane").style.zIndex = 450;
map.createPane("routePane");
map.getPane("routePane").style.zIndex = 650;
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 20,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const sourceControl = L.control({ position: "bottomleft" });
sourceControl.onAdd = () => {
  const div = L.DomUtil.create("div", "source-control");
  div.innerHTML = '<strong>Water level source</strong><span>Loading...</span>';
  return div;
};
sourceControl.addTo(map);

const layers = {
  floodPolygons: L.geoJSON(null, {
    pane: "floodPolygonPane",
    style: floodPolygonStyle,
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      layer.bindPopup(
        `<strong>Flood area:</strong> ${escapeHtml(p.road_name || "Unknown")}<br>` +
          `<strong>Time:</strong> ${escapeHtml(p.time || "")}<br>` +
          `<strong>Depth:</strong> ${formatDepth(p)}<br>` +
          `<strong>Risk factor:</strong> ${p.factor || 1}`,
      );
    },
  }).addTo(map),
  floodRoads: L.geoJSON(null, {
    pane: "floodPane",
    style: (feature) => floodRoadStyle(depthCm(feature.properties || {})),
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      layer.bindPopup(
        `<strong>Road:</strong> ${escapeHtml(p.road_name || "Unknown")}<br>` +
          `<strong>Time:</strong> ${escapeHtml(p.time || "")}<br>` +
          `<strong>Depth:</strong> ${formatDepth(p)}<br>` +
          `<strong>Factor:</strong> ${p.factor || 1}<br>` +
          `<strong>Vehicle:</strong> ${document.getElementById("vehicle").value}`,
      );
    },
  }).addTo(map),
  baseline: L.layerGroup().addTo(map),
  floodAware: L.layerGroup().addTo(map),
  overlaps: L.layerGroup().addTo(map),
  markers: L.layerGroup().addTo(map),
};

L.control
  .layers(
    null,
    {
      "Flood polygons": layers.floodPolygons,
      "Flooded roads": layers.floodRoads,
      "Baseline route": layers.baseline,
      "Flood-aware route": layers.floodAware,
      "Shared route": layers.overlaps,
      Markers: layers.markers,
    },
    { collapsed: false },
  )
  .addTo(map);

let pickMode = null;
let pickRouteStep = null;
let currentFloodTime = "";
let currentFloodSource = "";
let currentFloodLoadedAt = "";

function floodRoadStyle(depthCm) {
  let color = "#d9822b";
  if (depthCm < 5) color = "#d9a441";
  else if (depthCm < 15) color = "#ed8b2f";
  else if (depthCm < 20) color = "#d84a2b";
  else color = "#b91414";
  return { color, weight: 4, opacity: 0.78 };
}

function floodPolygonStyle(feature) {
  const depth = depthCm(feature.properties || {});
  let color = "#3399ff";
  let fillColor = "#66ccff";
  let fillOpacity = 0.25;
  if (depth >= 50) {
    color = "#003399";
    fillColor = "#003399";
    fillOpacity = 0.55;
  } else if (depth >= 20) {
    color = "#0066ff";
    fillColor = "#3399ff";
    fillOpacity = 0.42;
  }
  return { color, weight: 1, fillColor, fillOpacity };
}

function depthM(props) {
  const meters = Number(props.depth_m);
  if (Number.isFinite(meters)) return meters;
  const centimeters = Number(props.depth_cm);
  return Number.isFinite(centimeters) ? centimeters / 100 : 0;
}

function depthCm(props) {
  return depthM(props) * 100;
}

function formatDepth(propsOrMeters) {
  const meters = typeof propsOrMeters === "number" ? propsOrMeters : depthM(propsOrMeters || {});
  return `${meters.toFixed(2)} m (${Math.round(meters * 100)} cm)`;
}

function parsePoint(value) {
  const [lat, lon] = value.split(",").map((part) => Number(part.trim()));
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new Error("Bad coordinate input");
  return { lat, lon };
}

function valhallaShape(encoded) {
  if (!encoded) return [];
  let index = 0;
  let lat = 0;
  let lon = 0;
  const coordinates = [];
  const factor = 1e6;
  while (index < encoded.length) {
    let result = 1;
    let shift = 0;
    let b;
    do {
      b = encoded.charCodeAt(index++) - 63 - 1;
      result += b << shift;
      shift += 5;
    } while (b >= 0x1f);
    lat += result & 1 ? ~(result >> 1) : result >> 1;
    result = 1;
    shift = 0;
    do {
      b = encoded.charCodeAt(index++) - 63 - 1;
      result += b << shift;
      shift += 5;
    } while (b >= 0x1f);
    lon += result & 1 ? ~(result >> 1) : result >> 1;
    coordinates.push([lat / factor, lon / factor]);
  }
  return coordinates;
}

function routeShapeFromResponse(route) {
  return route?.json?.trip?.legs?.[0]?.shape || route?.trip?.legs?.[0]?.shape || "";
}

function drawRoute(group, encoded, color) {
  group.clearLayers();
  const coords = Array.isArray(encoded?.coordinates)
    ? encoded.coordinates.map(([lon, lat]) => [lat, lon])
    : valhallaShape(encoded);
  if (!coords.length) return null;
  const line = L.polyline(coords, { color, weight: 6, opacity: 0.94, pane: "routePane" }).addTo(group);
  return line;
}

function drawOverlaps(data) {
  layers.overlaps.clearLayers();
  const baselineCoords = routeCoords(data.baseline.route);
  const floodAwareCoords = routeCoords(data.flood_aware.route);
  drawSharedRouteSegments(baselineCoords, floodAwareCoords);
}

function drawSharedRouteSegments(baselineCoords, floodAwareCoords) {
  for (let i = 0; i < baselineCoords.length - 1; i += 1) {
    const a = baselineCoords[i];
    const b = baselineCoords[i + 1];
    if (segmentNearLine(a, b, floodAwareCoords, 7)) {
      L.polyline([a, b], {
        color: "#ffd400",
        weight: 9,
        opacity: 0.95,
        pane: "routePane",
      }).addTo(layers.overlaps);
    }
  }
}

function segmentNearLine(a, b, line, thresholdM) {
  for (let i = 0; i < line.length - 1; i += 1) {
    const c = line[i];
    const d = line[i + 1];
    if (segmentDistanceM(a, b, c, d) <= thresholdM) return true;
  }
  return false;
}

function routeCoords(route) {
  return shapeToCoords(routeShapeFromResponse(route));
}

function shapeToCoords(shape) {
  return Array.isArray(shape?.coordinates)
    ? shape.coordinates.map(([lon, lat]) => [lat, lon])
    : valhallaShape(shape);
}

function floodLinesWithProps(data) {
  return (data.linear_cost_factors.features || [])
    .map((feature) => ({
      coords: (feature.geometry?.coordinates || []).map(([lon, lat]) => [lat, lon]),
      props: feature.properties || {},
    }))
    .filter((item) => item.coords.length > 1);
}

function maxFloodDepthForCoords(coords, floodLines, thresholdM = 8) {
  let maxDepth = 0;
  let maxFactor = 0;
  let roadName = "";
  for (let i = 0; i < coords.length - 1; i += 1) {
    const a = coords[i];
    const b = coords[i + 1];
    for (const flood of floodLines) {
      if (segmentNearLine(a, b, flood.coords, thresholdM)) {
        const depth = depthM(flood.props);
        if (depth > maxDepth) {
          maxDepth = depth;
          maxFactor = Number(flood.props.factor || 0);
          roadName = flood.props.road_name || "";
        }
      }
    }
  }
  return { depthM: maxDepth, depthCm: maxDepth * 100, factor: maxFactor, roadName };
}

function segmentDistanceM(a, b, c, d) {
  const projected = projectSegments(a, b, c, d);
  if (segmentsIntersect(projected.a, projected.b, projected.c, projected.d)) return 0;
  if (!projectionOverlap(projected.a, projected.b, projected.c, projected.d)) return Infinity;
  return Math.min(
    pointToSegmentDistanceProjected(projected.a, projected.c, projected.d),
    pointToSegmentDistanceProjected(projected.b, projected.c, projected.d),
    pointToSegmentDistanceProjected(projected.c, projected.a, projected.b),
    pointToSegmentDistanceProjected(projected.d, projected.a, projected.b),
  );
}

function pointToSegmentDistanceM(p, a, b) {
  const projected = projectSegments(p, p, a, b);
  return pointToSegmentDistanceProjected(projected.a, projected.c, projected.d);
}

function projectSegments(a, b, c, d) {
  const midLat = (a[0] + b[0] + c[0] + d[0]) / 4;
  const lonM = 111320 * Math.cos((midLat * Math.PI) / 180);
  const latM = 111320;
  return {
    a: { x: a[1] * lonM, y: a[0] * latM },
    b: { x: b[1] * lonM, y: b[0] * latM },
    c: { x: c[1] * lonM, y: c[0] * latM },
    d: { x: d[1] * lonM, y: d[0] * latM },
  };
}

function pointToSegmentDistanceProjected(p, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (dx === 0 && dy === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

function projectionOverlap(a, b, c, d) {
  const ux = b.x - a.x;
  const uy = b.y - a.y;
  const lenSq = ux * ux + uy * uy;
  if (lenSq === 0) return false;
  const t0 = ((c.x - a.x) * ux + (c.y - a.y) * uy) / lenSq;
  const t1 = ((d.x - a.x) * ux + (d.y - a.y) * uy) / lenSq;
  return Math.max(0, Math.min(t0, t1)) <= Math.min(1, Math.max(t0, t1));
}

function segmentsIntersect(a, b, c, d) {
  const o1 = orientation(a, b, c);
  const o2 = orientation(a, b, d);
  const o3 = orientation(c, d, a);
  const o4 = orientation(c, d, b);
  return o1 * o2 < 0 && o3 * o4 < 0;
}

function orientation(a, b, c) {
  return Math.sign((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x));
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
  });
}

function setMarkers(origin, destination) {
  layers.markers.clearLayers();
  L.marker([origin.lat, origin.lon], { icon: pointIcon("S", "start") }).bindPopup("Start").addTo(layers.markers);
  L.marker([destination.lat, destination.lon], { icon: pointIcon("E", "end") }).bindPopup("End").addTo(layers.markers);
}

function setInputPoint(inputId, latlng) {
  document.getElementById(inputId).value = `${latlng.lat.toFixed(6)}, ${latlng.lng.toFixed(6)}`;
  refreshInputMarkers();
}

function refreshInputMarkers() {
  try {
    const origin = parsePoint(document.getElementById("origin").value);
    const destination = parsePoint(document.getElementById("destination").value);
    setMarkers(origin, destination);
  } catch {
    layers.markers.clearLayers();
  }
}

function setPickButtonState() {
  const twoPinButton = document.getElementById("pick-route-pins");
  twoPinButton.classList.toggle("active", Boolean(pickRouteStep));
  if (pickRouteStep === "origin") twoPinButton.textContent = "Click Start";
  else if (pickRouteStep === "destination") twoPinButton.textContent = "Click End";
  else twoPinButton.textContent = "Pick Start + End";
}

function pointIcon(label, type) {
  return L.divIcon({
    className: `point-marker ${type}`,
    html: `<span>${escapeHtml(label)}</span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    popupAnchor: [0, -16],
  });
}

async function getJson(path, options) {
  const res = await fetch(`${API}${path}`, options);
  if (!res.ok) throw new Error(`${path} ${res.status}`);
  return res.json();
}

async function loadTimesteps() {
  const data = await getJson("/flood/timesteps");
  currentFloodTime = data.latest_timestep || data.timesteps?.[data.timesteps.length - 1] || "";
  updateFloodSourceInfo(data);
}

function updateFloodSourceInfo(data) {
  const el = document.querySelector(".source-control");
  if (!el) return;
  const source = data.flood_geojson_source || "unknown";
  const loadedAt = data.flood_geojson_loaded_at || "";
  const modified = data.flood_geojson_last_modified || "";
  const fileName = source.split(/[\\/]/).pop() || source;
  currentFloodSource = fileName;
  currentFloodLoadedAt = loadedAt;
  const title = modified ? `Modified: ${formatTimestamp(modified)}` : source;
  el.innerHTML = `
    <strong>Water level source</strong>
    <span title="${escapeHtml(source)}">${escapeHtml(fileName)}</span>
    <small title="${escapeHtml(title)}">Pulled ${escapeHtml(formatTimestamp(loadedAt))}</small>
    <small>Latest flood time ${escapeHtml(formatTimestamp(data.latest_timestep || currentFloodTime))}</small>
  `;
}

function formatTimestamp(value) {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function loadFloodLayers() {
  const time = currentFloodTime;
  const vehicle = document.getElementById("vehicle").value;
  document.getElementById("result").innerHTML = `<div class="badge neutral">LOADING</div><p>Flood time: ${escapeHtml(time || "n/a")}</p>`;
  const query = `time=${encodeURIComponent(time)}&vehicle_type=${encodeURIComponent(vehicle)}`;
  const [polygons, roads] = await Promise.all([
    getJson(`/flood/polygons?${query}`),
    getJson(`/flood/roads?${query}`),
  ]);
  layers.floodPolygons.clearLayers();
  layers.floodPolygons.addData(polygons);
  layers.floodRoads.clearLayers();
  layers.floodRoads.addData(roads);
  fitFloodBounds();
  renderFloodLoadResult(polygons, roads, time, vehicle);
}

function fitFloodBounds() {
  const bounds = L.latLngBounds([]);
  [layers.floodPolygons, layers.floodRoads].forEach((group) => {
    group.eachLayer((layer) => {
      if (layer.getBounds) bounds.extend(layer.getBounds());
      else if (layer.getLatLng) bounds.extend(layer.getLatLng());
    });
  });
  if (bounds.isValid()) map.fitBounds(bounds.pad(0.12));
}

function renderFloodLoadResult(polygons, roads, time, vehicle) {
  const polygonCount = polygons.features?.length || 0;
  const roadCount = roads.features?.length || 0;
  document.getElementById("result").innerHTML = `
    <div class="badge neutral">LOADED</div>
    <div class="metric-grid">
      <div class="metric"><strong>Vehicle</strong>${escapeHtml(vehicle)}</div>
      <div class="metric"><strong>Flood time</strong>${escapeHtml(formatTimestamp(time))}</div>
      <div class="metric"><strong>Flood roads</strong>${roadCount}</div>
      <div class="metric"><strong>Flood polygons</strong>${polygonCount}</div>
      <div class="metric"><strong>File</strong>${escapeHtml(currentFloodSource || "n/a")}</div>
      <div class="metric"><strong>Pulled</strong>${escapeHtml(formatTimestamp(currentFloodLoadedAt))}</div>
    </div>
  `;
}

async function runCompare() {
  const origin = parsePoint(document.getElementById("origin").value);
  const destination = parsePoint(document.getElementById("destination").value);
  const vehicle = document.getElementById("vehicle").value;
  const floodTime = currentFloodTime;
  document.getElementById("result").innerHTML = `
    <div class="badge neutral">ROUTING</div>
    <p>Calculating custom route...</p>
  `;
  setMarkers(origin, destination);

  const payload = {
    origin,
    destination,
    vehicle_type: vehicle,
    flood_time_step: floodTime,
  };
  const data = await getJson("/route/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  layers.floodRoads.clearLayers();
  layers.floodRoads.addData({ type: "FeatureCollection", features: data.linear_cost_factors.features || [] });

  const baselineLine = drawRoute(layers.baseline, routeShapeFromResponse(data.baseline.route), "#1b66d2");
  const floodLine = drawRoute(layers.floodAware, routeShapeFromResponse(data.flood_aware.route), "#1f8a4c");
  drawOverlaps(data);
  const bounds = L.latLngBounds([]);
  if (baselineLine) bounds.extend(baselineLine.getBounds());
  if (floodLine) bounds.extend(floodLine.getBounds());
  layers.markers.eachLayer((layer) => bounds.extend(layer.getLatLng()));
  if (bounds.isValid()) map.fitBounds(bounds.pad(0.18));

  renderResult(data);
}

function renderResult(data) {
  const badgeClass = data.result === "PASS" ? "pass" : data.result === "FAIL" ? "fail" : "neutral";
  document.getElementById("result").innerHTML = `
    <div class="badge ${badgeClass}">${escapeHtml(data.result)}</div>
    <div class="legend">
      <span><i class="swatch baseline"></i>Baseline</span>
      <span><i class="swatch flood-aware"></i>Flood-aware</span>
      <span><i class="swatch shared"></i>Shared route</span>
      <span><i class="swatch flood-polygon"></i>Flood polygon</span>
      <span><i class="swatch flood-road"></i>Flood road</span>
    </div>
    <details class="panel-section result-section" open>
      <summary>Route Metrics</summary>
      <div class="metric-grid">
        <div class="metric"><strong>Vehicle</strong>${escapeHtml(data.vehicle_type)}</div>
        <div class="metric"><strong>Time</strong>${escapeHtml(data.flood_time_step)}</div>
        <div class="metric"><strong>Affected roads</strong>${data.linear_cost_factors.count}</div>
        <div class="metric"><strong>Hard-blocked</strong>${data.hard_exclusions?.count || 0} points / ${data.hard_exclusions?.feature_count || 0} roads</div>
        <div class="metric"><strong>Max factor</strong>${data.linear_cost_factors.max_factor}</div>
        <div class="metric"><strong>Baseline</strong>${fmt(data.baseline.distance_km)} km / ${fmt(data.baseline.duration_min)} min</div>
        <div class="metric"><strong>Flood-aware</strong>${fmt(data.flood_aware.distance_km)} km / ${fmt(data.flood_aware.duration_min)} min</div>
        <div class="metric"><strong>Baseline depth</strong>${formatDepth(data.baseline.max_depth_m ?? (data.baseline.max_depth_cm || 0) / 100)}</div>
        <div class="metric"><strong>Flood-aware depth</strong>${formatDepth(data.flood_aware.max_depth_m ?? (data.flood_aware.max_depth_cm || 0) / 100)}</div>
      </div>
      <div class="warning">${escapeHtml(data.reason)} ${escapeHtml(data.decision)}</div>
    </details>
    ${renderDirections(data)}
  `;
}

function renderDirections(data) {
  return `
    <details class="panel-section directions-panel">
      <summary>Directions Comparison</summary>
      <div class="direction-columns">
        ${renderRouteDirections("Baseline", data.baseline.route, data, "baseline")}
        ${renderRouteDirections("Flood-aware", data.flood_aware.route, data, "flood-aware")}
      </div>
    </details>
  `;
}

function renderRouteDirections(title, route, data, className) {
  const leg = route?.json?.trip?.legs?.[0];
  const maneuvers = leg?.maneuvers || [];
  const coords = routeCoords(route);
  const floodLines = floodLinesWithProps(data);
  const items = maneuvers
    .filter((maneuver) => maneuver.type !== 4)
    .map((maneuver, index) => {
      const start = Math.max(0, Number(maneuver.begin_shape_index || 0));
      const end = Math.max(start + 1, Number(maneuver.end_shape_index || start + 1));
      const maneuverCoords = coords.slice(start, Math.min(end + 1, coords.length));
      const flood = maxFloodDepthForCoords(maneuverCoords, floodLines);
      return `
        <li>
          <div class="step-top">
            <span class="step-number">${index + 1}</span>
            <span class="step-instruction">${escapeHtml(maneuver.instruction || "Continue")}</span>
          </div>
          <div class="step-meta">
            <span>${fmt(maneuver.length)} km</span>
            <span>${fmt((maneuver.time || 0) / 60)} min</span>
            <span class="${flood.depthM >= 0.2 ? "depth dangerous" : flood.depthM > 0 ? "depth wet" : "depth dry"}">
              Water ${formatDepth(flood.depthM)}
            </span>
            ${flood.roadName ? `<span title="${escapeHtml(flood.roadName)}">Factor ${flood.factor}</span>` : ""}
          </div>
        </li>
      `;
    })
    .join("");
  return `
    <article class="direction-card ${className}">
      <h3>${escapeHtml(title)}</h3>
      <ol>${items || "<li>No directions returned.</li>"}</ol>
    </article>
  `;
}

function fmt(value) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(2) : "n/a";
}

map.on("click", (event) => {
  if (pickRouteStep) {
    setInputPoint(pickRouteStep, event.latlng);
    pickRouteStep = pickRouteStep === "origin" ? "destination" : null;
    setPickButtonState();
    return;
  }
  if (!pickMode) return;
  setInputPoint(pickMode, event.latlng);
  pickMode = null;
});

document.getElementById("pick-origin").addEventListener("click", () => {
  pickMode = "origin";
  pickRouteStep = null;
  setPickButtonState();
});
document.getElementById("pick-destination").addEventListener("click", () => {
  pickMode = "destination";
  pickRouteStep = null;
  setPickButtonState();
});
document.getElementById("pick-route-pins").addEventListener("click", () => {
  pickMode = null;
  pickRouteStep = pickRouteStep ? null : "origin";
  setPickButtonState();
});
document.getElementById("vehicle").addEventListener("change", () => {
  loadFloodLayers().catch((error) => {
    document.getElementById("result").innerHTML = `<div class="badge fail">ERROR</div><p>${escapeHtml(error.message)}</p>`;
  });
});
document.getElementById("route").addEventListener("click", () => {
  runCompare().catch((error) => {
    document.getElementById("result").innerHTML = `<div class="badge fail">ERROR</div><p>${escapeHtml(error.message)}</p>`;
  });
});

loadTimesteps()
  .then(loadFloodLayers)
  .catch((error) => {
    document.getElementById("result").innerHTML = `<div class="badge fail">ERROR</div><p>${escapeHtml(error.message)}</p>`;
  });
