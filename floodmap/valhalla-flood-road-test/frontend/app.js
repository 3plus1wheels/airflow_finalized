const API = window.FLOOD_API_BASE || "/api";

const VEHICLE_ORDER = ["motorbike", "car", "truck"];
const DEFAULT_VEHICLES = {
  motorbike: { label_vi: "Xe máy", label_en: "Motorbike", threshold_cm: 20 },
  car: { label_vi: "Ô tô", label_en: "Car", threshold_cm: 30 },
  truck: { label_vi: "Xe tải", label_en: "Truck", threshold_cm: 50 },
};
const ROUTE_STYLES = {
  recommended: { color: "#00b8ff", label: "Optimal flood-aware" },
  alternate: { color: "#ff2d95", label: "Alternative" },
  alternateWarm: { color: "#ff9f1c", label: "Alternative" },
};
const ROUTE_FALLBACKS = [ROUTE_STYLES.recommended, ROUTE_STYLES.alternate, ROUTE_STYLES.alternateWarm];

const state = {
  activeVehicle: "motorbike",
  activeRouteByVehicle: {},
  forecast: null,
  pickMode: null,
  pickRouteStep: null,
  currentFloodTime: "",
  currentFloodSource: "",
  currentFloodLoadedAt: "",
  availableFloodTimesteps: [],
  floodSourceMode: "rain",
};

const map = L.map("map", { zoomControl: false }).setView([21.0219, 105.763], 16);
map.createPane("floodPolygonPane");
map.getPane("floodPolygonPane").style.zIndex = 430;
map.createPane("floodPane");
map.getPane("floodPane").style.zIndex = 450;
map.createPane("routePane");
map.getPane("routePane").style.zIndex = 650;
L.control.zoom({ position: "topright" }).addTo(map);
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
        renderFloodPopup("Flood area", [
          ["Road", p.road_name || "Unknown"],
          ["Time", formatTimestamp(p.time || "")],
          ["Depth", formatDepth(p)],
        ]),
      );
    },
  }).addTo(map),
  floodRoads: L.geoJSON(null, {
    pane: "floodPane",
    style: (feature) => floodRoadStyle(depthCm(feature.properties || {})),
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      layer.bindPopup(
        renderFloodPopup("Flooded road", [
          ["Road", p.road_name || "Unknown"],
          ["Time", formatTimestamp(p.time || "")],
          ["Depth", formatDepth(p)],
          ["Vehicle", activeVehicleLabel()],
        ]),
      );
    },
  }),
  routes: L.layerGroup().addTo(map),
  markers: L.layerGroup().addTo(map),
};

L.control
  .layers(
    null,
    {
      "Flood surface": layers.floodPolygons,
      "Road detail": layers.floodRoads,
      Routes: layers.routes,
      Markers: layers.markers,
    },
    { collapsed: true },
  )
  .addTo(map);

function floodRoadStyle(depthCmValue) {
  let color = "#8ee8ff";
  if (depthCmValue >= 50) color = "#06306f";
  else if (depthCmValue >= 30) color = "#0b5fc6";
  else if (depthCmValue >= 20) color = "#1c93e8";
  else if (depthCmValue >= 10) color = "#58c7f4";
  return {
    color,
    weight: 2,
    opacity: 0.5,
    lineCap: "round",
    lineJoin: "round",
  };
}

function floodPolygonStyle(feature) {
  const depth = depthCm(feature.properties || {});
  let color = "#8bd7f0";
  let fillColor = "#9ee8ff";
  let fillOpacity = 0.36;
  if (depth >= 50) {
    color = "#062a64";
    fillColor = "#08357f";
    fillOpacity = 0.68;
  } else if (depth >= 30) {
    color = "#084aa0";
    fillColor = "#0b5fc6";
    fillOpacity = 0.58;
  } else if (depth >= 20) {
    color = "#117bd1";
    fillColor = "#1c93e8";
    fillOpacity = 0.5;
  } else if (depth >= 10) {
    color = "#3fb5e7";
    fillColor = "#58c7f4";
    fillOpacity = 0.43;
  }
  return {
    color,
    stroke: false,
    weight: 0,
    opacity: 0,
    fillColor,
    fillOpacity,
    lineCap: "round",
    lineJoin: "round",
  };
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

function renderFloodPopup(title, rows) {
  return `
    <section class="flood-popup">
      <h2>${escapeHtml(title)}</h2>
      <dl>
        ${rows
          .map(([label, value]) => `
            <div>
              <dt>${escapeHtml(label)}</dt>
              <dd>${escapeHtml(value || "n/a")}</dd>
            </div>
          `)
          .join("")}
      </dl>
    </section>
  `;
}

function parsePoint(value) {
  const [lat, lon] = value.split(",").map((part) => Number(part.trim()));
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new Error("Bad coordinate input");
  return { lat, lon };
}

function pointParam(point) {
  return `${point.lat},${point.lon}`;
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

function shapeToCoords(shape) {
  if (Array.isArray(shape?.coordinates)) {
    return shape.coordinates.map(([lon, lat]) => [lat, lon]);
  }
  return valhallaShape(shape);
}

function routeCoords(route) {
  return shapeToCoords(routeShapeFromResponse(route));
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
  twoPinButton.classList.toggle("active", Boolean(state.pickRouteStep));
  if (state.pickRouteStep === "origin") twoPinButton.textContent = "Chọn điểm đi / Pick start";
  else if (state.pickRouteStep === "destination") twoPinButton.textContent = "Chọn điểm đến / Pick end";
  else twoPinButton.textContent = "Chọn 2 điểm / Pick both";
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
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || body.detail || `${path} ${res.status}`);
  }
  return res.json();
}

async function loadTimesteps() {
  const modeQuery = state.floodSourceMode === "rain" ? "?mode=nonempty" : "";
  const data = await getJson(`/flood/timesteps${modeQuery}`);
  state.availableFloodTimesteps = Array.isArray(data.timesteps) ? data.timesteps : [];
  state.currentFloodTime = data.latest_timestep || data.timesteps?.[data.timesteps.length - 1] || "";
  updateFloodSourceInfo(data);
}

function snapDepartureToFloodWindowStart() {
  const firstStep = state.availableFloodTimesteps[0] || state.currentFloodTime;
  const value = timestepToInputValue(firstStep);
  if (value) document.getElementById("departure").value = value;
}

function timestepToInputValue(value) {
  const match = String(value || "").match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/);
  return match ? match[1] : "";
}

function updateFloodSourceInfo(data) {
  const el = document.querySelector(".source-control");
  if (!el) return;
  const source = data.flood_geojson_source || "unknown";
  const loadedAt = data.flood_geojson_loaded_at || "";
  const modified = data.flood_geojson_last_modified || "";
  const fileName = source.split(/[\\/]/).pop() || source;
  state.currentFloodSource = fileName;
  state.currentFloodLoadedAt = loadedAt;
  const title = modified ? `Modified: ${formatTimestamp(modified)}` : source;
  el.innerHTML = `
    <strong>Water level source</strong>
    <span title="${escapeHtml(source)}">${escapeHtml(fileName)}</span>
    <small>${state.floodSourceMode === "rain" ? "Latest rain/non-empty file" : "Latest available file"}</small>
    <small title="${escapeHtml(title)}">Pulled ${escapeHtml(formatTimestamp(loadedAt))}</small>
    <small>Latest flood time ${escapeHtml(formatTimestamp(data.latest_timestep || state.currentFloodTime))}</small>
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
  const time = state.currentFloodTime;
  const vehicle = state.activeVehicle;
  if (!time) {
    layers.floodPolygons.clearLayers();
    layers.floodRoads.clearLayers();
    return;
  }
  const sourceMode = state.floodSourceMode === "rain" ? "nonempty" : "latest";
  const query = `time=${encodeURIComponent(time)}&vehicle_type=${encodeURIComponent(vehicle)}&mode=${encodeURIComponent(sourceMode)}`;
  const [polygons, roads] = await Promise.all([
    getJson(`/flood/polygons?${query}`),
    getJson(`/flood/roads?${query}`),
  ]);
  layers.floodPolygons.clearLayers();
  layers.floodPolygons.addData(polygons);
  layers.floodRoads.clearLayers();
  layers.floodRoads.addData(roads);
}

async function runForecast() {
  const origin = parsePoint(document.getElementById("origin").value);
  const destination = parsePoint(document.getElementById("destination").value);
  setMarkers(origin, destination);
  renderStatus("neutral", "ROUTING", "Đang tính tuyến / Calculating route...");

  const params = new URLSearchParams({
    origin: pointParam(origin),
    destination: pointParam(destination),
    departure_time: departureApiValue(),
    mode: state.floodSourceMode === "rain" ? "nonempty" : "latest",
    alternates: "2",
    force: "true",
  });
  const data = await getJson(`/flood/route/forecast?${params.toString()}`);
  state.forecast = data;
  state.currentFloodTime = data.latest_timestep || data.flood_time_step || "";
  updateFloodSourceInfo(data);
  ensureSelectedRoutes();
  renderForecast();
  drawRoutes(true);
  if (!data.latest_timestep) {
    renderStatus("neutral", "NO FLOOD DATA", "Latest GeoJSON has no flood timesteps");
  } else if (data.is_stale) {
    renderStatus("neutral", "STALE DATA", "Dùng timestep gần nhất / Using nearest available timestep");
  } else {
    renderStatus("pass", "READY", "Dữ liệu theo khung giờ / Timed forecast ready");
  }
}

function departureApiValue() {
  const value = document.getElementById("departure").value || localDateTimeValue(new Date());
  const date = new Date(value);
  if (!Number.isNaN(date.getTime())) return date.toISOString().slice(0, 19);
  return value.length === 16 ? `${value}:00` : value;
}

function localDateTimeValue(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function ensureSelectedRoutes() {
  const forecast = state.forecast;
  if (!forecast) return;
  VEHICLE_ORDER.forEach((vehicle) => {
    const routes = forecast.routes_by_vehicle?.[vehicle] || [];
    const current = state.activeRouteByVehicle[vehicle];
    const exists = routes.some((route) => route.id === current);
    state.activeRouteByVehicle[vehicle] = exists
      ? current
      : forecast.vehicles?.[vehicle]?.selected_route_id || routes[0]?.id || "";
  });
}

function renderForecast() {
  renderVehicleTabs();
  renderBestDeparture();
  renderHistogram();
  renderRouteOptions();
  renderDirections();
  drawRoutes(false);
}

function renderVehicleTabs() {
  const container = document.getElementById("vehicle-tabs");
  const vehicles = state.forecast?.vehicles || DEFAULT_VEHICLES;
  container.innerHTML = VEHICLE_ORDER.map((vehicle) => {
    const item = vehicles[vehicle] || DEFAULT_VEHICLES[vehicle];
    const eta = item.eta_min ? `${Math.round(item.eta_min)} phút / min` : "--";
    const active = vehicle === state.activeVehicle ? "active" : "";
    return `
      <button class="${active}" type="button" data-vehicle="${escapeHtml(vehicle)}">
        <span>${escapeHtml(item.label_vi || DEFAULT_VEHICLES[vehicle].label_vi)}</span>
        <strong>${escapeHtml(eta)}</strong>
        <small>${escapeHtml(item.label_en || DEFAULT_VEHICLES[vehicle].label_en)}</small>
      </button>
    `;
  }).join("");
}

function renderBestDeparture() {
  const best = state.forecast?.best_departure?.[state.activeVehicle];
  const threshold = state.forecast?.thresholds_cm?.[state.activeVehicle] || DEFAULT_VEHICLES[state.activeVehicle].threshold_cm;
  document.getElementById("best-departure").textContent = best
    ? `${best.label_vi} / ${best.label_en}`
    : "đi ngay / go now";
  document.getElementById("threshold-label").textContent = `${Math.round(threshold)} cm`;
  if (best?.status === "none") {
    document.getElementById("best-departure").textContent =
      "khong co khung an toan trong 4h hien thi / no safe 30-min window in visible 4h";
  } else if (best?.outside_visible) {
    document.getElementById("best-departure").textContent =
      "khung an toan nam ngoai 4h hien thi / safe window outside visible 4h";
  }
}

function renderHistogram() {
  const container = document.getElementById("water-histogram");
  const bars = (state.forecast?.forecast_by_vehicle?.[state.activeVehicle] || []).slice(0, 8);
  const threshold = state.forecast?.thresholds_cm?.[state.activeVehicle] || DEFAULT_VEHICLES[state.activeVehicle].threshold_cm;
  if (!bars.length) {
    container.innerHTML = `<div class="empty-state">Chưa có dự báo / No forecast</div>`;
    return;
  }
  const maxDepth = Math.max(threshold * 1.25, 40, ...bars.map((bar) => Number(bar.depth_cm) || 0));
  const thresholdBottom = Math.min(100, Math.max(0, (threshold / maxDepth) * 100));
  const labels = bars
    .filter((bar) => bar.index % 2 === 0)
    .map((bar) => `<span style="grid-column:${bar.index + 1} / span 2">${escapeHtml(bar.label)}</span>`)
    .join("");
  container.innerHTML = `
    <div class="histogram-meta">4h route-depth forecast / du bao do sau tren tuyen 4h</div>
    <div class="histogram-chart" style="--threshold-bottom:${thresholdBottom}%; --histogram-scale:${maxDepth};">
      <div class="threshold-line" aria-hidden="true"></div>
      <div class="histogram-bars">
        ${bars.map((bar) => renderHistogramBar(bar, maxDepth)).join("")}
      </div>
      <div class="histogram-labels">${labels}</div>
    </div>
    <div class="histogram-legend">
      <span><i class="severity low"></i>&lt;10cm</span>
      <span><i class="severity moderate"></i>10-20cm</span>
      <span><i class="severity high"></i>20-30cm</span>
      <span><i class="severity severe"></i>&gt;30cm</span>
    </div>
  `;
}

function renderHistogramBar(bar, maxDepth) {
  const depth = Number(bar.depth_cm) || 0;
  const height = Math.max(8, Math.min(100, (depth / maxDepth) * 100));
  const classes = ["water-bar", bar.severity || "low"];
  if (bar.is_now) classes.push("now");
  if (!bar.safe) classes.push("unsafe");
  if (height >= 24 && depth > 0) classes.push("show-value");
  const valueLabel = depth >= 100 ? `${Math.round(depth)}` : depth.toFixed(depth < 10 ? 1 : 0);
  return `
    <button class="${classes.join(" ")}" type="button" title="${escapeHtml(bar.label)}: ${depth.toFixed(1)} cm" style="--bar-height:${height}%">
      <span class="bar-value">${escapeHtml(valueLabel)}<small>cm</small></span>
    </button>
  `;
}

function renderRouteOptions() {
  const container = document.getElementById("route-options");
  const routes = activeRoutes();
  document.getElementById("route-count").textContent = `${routes.length} routes`;
  if (!routes.length) {
    container.innerHTML = `<div class="empty-state">Không có tuyến / No route</div>`;
    return;
  }
  const selectedId = activeRouteId();
  container.innerHTML = routes.map((route, index) => {
    const active = route.id === selectedId ? "active" : "";
    const depthClass = route.crosses_threshold ? "danger" : "safe";
    const style = routeStyle(route, index);
    const label = routeDisplayLabel(index);
    return `
      <button class="route-card ${active}" type="button" data-route-id="${escapeHtml(route.id)}" style="--route-accent:${style.color}">
        <span class="route-card-color"></span>
        <span>
          <strong>${escapeHtml(label.vi)} / ${escapeHtml(label.en)}</strong>
          <small>${formatMinutes(route.duration_min)} • ${formatKm(route.distance_km)}</small>
        </span>
        <em class="${depthClass}">max ${formatCm(route.max_depth_cm)}</em>
      </button>
    `;
  }).join("");
}

function renderDirections() {
  const selected = activeRoute();
  const summary = document.getElementById("route-summary");
  const directions = document.getElementById("directions");
  if (!selected) {
    summary.textContent = "No route yet";
    directions.innerHTML = "";
    return;
  }
  summary.textContent = `${formatMinutes(selected.duration_min)} • ${formatKm(selected.distance_km)} • max ${formatCm(selected.max_depth_cm)}`;
  const maneuvers = selected.route?.json?.trip?.legs?.[0]?.maneuvers || [];
  directions.innerHTML = maneuvers
    .filter((maneuver) => maneuver.type !== 4)
    .map((maneuver, index) => renderDirectionStep(maneuver, index) || `
      <li>
        <span>${index + 1}</span>
        <p>${escapeHtml(maneuver.instruction || "Continue")}</p>
        <small>${formatKm(maneuver.length)} • ${formatMinutes((maneuver.time || 0) / 60)}</small>
      </li>
    `)
    .join("") || `<li><p>No directions returned.</p></li>`;
}

function renderDirectionStep(maneuver, index) {
  const depth = Number(maneuver.max_depth_cm);
  const depthChip = Number.isFinite(depth) && depth > 0
    ? `<span class="depth-chip ${depthClass(depth)}">depth ${formatCm(depth)}</span>`
    : "";
  return `
    <li>
      <span>${index + 1}</span>
      <p>${escapeHtml(maneuver.instruction || "Continue")}</p>
      <small class="direction-meta">
        <span>${formatKm(maneuver.length)}</span>
        <span>${formatMinutes((maneuver.time || 0) / 60)}</span>
        ${depthChip}
      </small>
    </li>
  `;
}

function depthClass(depthCmValue) {
  if (depthCmValue >= 50) return "extreme";
  if (depthCmValue >= 30) return "severe";
  if (depthCmValue >= 20) return "high";
  if (depthCmValue >= 10) return "moderate";
  return "low";
}

function drawRoutes(shouldFit) {
  layers.routes.clearLayers();
  const routes = activeRoutes();
  const selectedId = activeRouteId();
  const bounds = L.latLngBounds([]);

  routes
    .slice()
    .sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId))
    .forEach((route, index) => {
      const coords = routeCoords(route.route);
      if (!coords.length) return;
      const selected = route.id === selectedId;
      const routeIndex = routes.findIndex((item) => item.id === route.id);
      const style = routeStyle(route, routeIndex);
      L.polyline(coords, {
        color: "#102027",
        weight: selected ? 13 : 11,
        opacity: selected ? 0.7 : 0.62,
        pane: "routePane",
        interactive: false,
      }).addTo(layers.routes);
      const line = L.polyline(coords, {
        color: style.color,
        weight: selected ? 9 : 7,
        opacity: 1,
        pane: "routePane",
      }).addTo(layers.routes);
      line.on("click", () => {
        state.activeRouteByVehicle[state.activeVehicle] = route.id;
        renderForecast();
      });
      line.bindTooltip(
        `${style.label}: ${formatMinutes(route.duration_min)} - max ${formatCm(route.max_depth_cm)}`,
        { className: "route-tooltip", sticky: true },
      );
      bounds.extend(line.getBounds());
    });

  layers.markers.eachLayer((layer) => bounds.extend(layer.getLatLng()));
  if (shouldFit && bounds.isValid()) map.fitBounds(bounds.pad(0.18));
}

function routeStyle(route, index) {
  const routeOrderStyle = ROUTE_FALLBACKS[Math.max(0, index) % ROUTE_FALLBACKS.length];
  if (Number.isFinite(index)) return routeOrderStyle;
  const source = String(route?.source || route?.label_en || route?.label_vi || "").toLowerCase();
  if (source.includes("fast")) return ROUTE_STYLES.alternateWarm;
  if (source.includes("alternate") || source.includes("other") || source.includes("khac")) {
    return ROUTE_STYLES.alternate;
  }
  if (source.includes("recommend") || source.includes("safe") || source.includes("flood")) {
    return ROUTE_STYLES.recommended;
  }
  return ROUTE_STYLES.recommended;
}

function routeDisplayLabel(index) {
  return index === 0
    ? { vi: "De xuat", en: "Recommended" }
    : { vi: "Tuyen khac", en: "Alternative" };
}

function activeRoutes() {
  return state.forecast?.routes_by_vehicle?.[state.activeVehicle] || [];
}

function activeRouteId() {
  return state.activeRouteByVehicle[state.activeVehicle] || activeRoutes()[0]?.id || "";
}

function activeRoute() {
  const id = activeRouteId();
  return activeRoutes().find((route) => route.id === id) || activeRoutes()[0] || null;
}

function activeVehicleLabel() {
  const vehicle = state.forecast?.vehicles?.[state.activeVehicle] || DEFAULT_VEHICLES[state.activeVehicle];
  return `${vehicle.label_vi || ""} / ${vehicle.label_en || ""}`;
}

function renderStatus(kind, title, message) {
  document.getElementById("status-panel").innerHTML = `
    <div class="badge ${kind}">${escapeHtml(title)}</div>
    <p>${escapeHtml(message)}</p>
  `;
}

function syncSourceButton() {
  const button = document.getElementById("rain-source");
  button.classList.toggle("active", state.floodSourceMode === "rain");
  button.textContent = state.floodSourceMode === "rain" ? "File mới" : "Mưa";
}

function formatMinutes(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-- min";
  return `${Math.max(1, Math.round(number))} min`;
}

function formatKm(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-- km";
  return `${number.toFixed(2)} km`;
}

function formatCm(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-- cm";
  return `${Math.round(number)} cm`;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
  });
}

map.on("click", (event) => {
  if (state.pickRouteStep) {
    setInputPoint(state.pickRouteStep, event.latlng);
    state.pickRouteStep = state.pickRouteStep === "origin" ? "destination" : null;
    setPickButtonState();
    return;
  }
  if (!state.pickMode) return;
  setInputPoint(state.pickMode, event.latlng);
  state.pickMode = null;
});

document.getElementById("origin").addEventListener("change", refreshInputMarkers);
document.getElementById("destination").addEventListener("change", refreshInputMarkers);
document.getElementById("pick-origin").addEventListener("click", () => {
  state.pickMode = "origin";
  state.pickRouteStep = null;
  setPickButtonState();
});
document.getElementById("pick-destination").addEventListener("click", () => {
  state.pickMode = "destination";
  state.pickRouteStep = null;
  setPickButtonState();
});
document.getElementById("pick-route-pins").addEventListener("click", () => {
  state.pickMode = null;
  state.pickRouteStep = state.pickRouteStep ? null : "origin";
  setPickButtonState();
});
document.getElementById("route").addEventListener("click", () => {
  loadTimesteps()
    .then(loadFloodLayers)
    .then(runForecast)
    .catch((error) => renderStatus("fail", "ERROR", error.message));
});
document.getElementById("rain-source").addEventListener("click", () => {
  state.floodSourceMode = state.floodSourceMode === "rain" ? "latest" : "rain";
  syncSourceButton();
  loadTimesteps()
    .then(() => snapDepartureToFloodWindowStart())
    .then(loadFloodLayers)
    .then(runForecast)
    .catch((error) => renderStatus("fail", "ERROR", error.message));
});
document.getElementById("vehicle-tabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-vehicle]");
  if (!button) return;
  state.activeVehicle = button.dataset.vehicle;
  ensureSelectedRoutes();
  renderForecast();
});
document.getElementById("route-options").addEventListener("click", (event) => {
  const button = event.target.closest("[data-route-id]");
  if (!button) return;
  state.activeRouteByVehicle[state.activeVehicle] = button.dataset.routeId;
  renderForecast();
});

document.getElementById("departure").value = localDateTimeValue(new Date());
refreshInputMarkers();
renderVehicleTabs();
syncSourceButton();

loadTimesteps()
  .then(loadFloodLayers)
  .then(runForecast)
  .catch((error) => renderStatus("fail", "ERROR", error.message));
