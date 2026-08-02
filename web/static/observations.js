const queryForm = document.querySelector("#station-query-form");
const stationInput = document.querySelector("#surface-station");
const dateInput = document.querySelector("#surface-date");
const dateWrap = document.querySelector("#history-date-wrap");
const realtimePanel = document.querySelector("#realtime-panel");
const resultSection = document.querySelector("#station-image-result");
const resultState = document.querySelector("#station-image-state");
const chartWrap = document.querySelector("#observation-dynamic-chart");
const chart = document.querySelector("#station-observation-chart");
const downloadButton = document.querySelector("#station-image-download");
const resultTitle = document.querySelector("#station-image-title");
const resultSource = document.querySelector("#station-image-source");
const stationOptions = document.querySelector("#surface-station-options");
const regionTabs = document.querySelector("#station-region-tabs");
const regionMap = document.querySelector("#station-region-map");
const regionStatus = document.querySelector("#station-region-status");
const SVG_NS = "http://www.w3.org/2000/svg";
const REGIONS = ["华东", "华北", "东北", "华中", "华南", "西南", "西北"];

let stationSearchTimer = null;
let latestSeries = null;

function localIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function selectedMode() {
  return queryForm.elements.mode.value;
}

function updateMode() {
  const historical = selectedMode() === "history";
  dateWrap.hidden = !historical;
  dateInput.required = historical;
  dateInput.disabled = !historical;
}

function formatValue(value, digits, suffix = "") {
  return Number.isFinite(Number(value))
    ? `${Number(value).toFixed(digits)}${suffix}`
    : "—";
}

function windDirectionName(degrees) {
  if (!Number.isFinite(Number(degrees))) return "风向缺测";
  const names = [
    "北风", "北偏东北风", "东北风", "东北偏东风",
    "东风", "东南偏东风", "东南风", "南偏东南风",
    "南风", "南偏西南风", "西南风", "西南偏西风",
    "西风", "西北偏西风", "西北风", "西北偏北风",
  ];
  return names[Math.round((Number(degrees) % 360) / 22.5) % 16];
}

function compass(degrees) {
  if (!Number.isFinite(Number(degrees))) return "—";
  const names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  return names[Math.round(Number(degrees) / 22.5) % 16];
}

function svg(name, attributes = {}, text = "") {
  const element = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
  if (text) element.textContent = text;
  return element;
}

function finiteValues(points, key) {
  return points.map((item) => Number(item[key])).filter(Number.isFinite);
}

function paddedExtent(values, padding = 0.12) {
  if (!values.length) return [0, 1];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const span = Math.max(maximum - minimum, 1);
  return [minimum - span * padding, maximum + span * padding];
}

function linePath(points, key, x, y) {
  let drawing = false;
  return points.map((point, index) => {
    const value = Number(point[key]);
    if (!Number.isFinite(value)) {
      drawing = false;
      return "";
    }
    const prefix = drawing ? "L" : "M";
    drawing = true;
    return `${prefix}${x(index).toFixed(1)},${y(value).toFixed(1)}`;
  }).join(" ");
}

function apparentTemperature(temperature, humidity) {
  const t = Number(temperature);
  const rh = Number(humidity);
  if (!Number.isFinite(t) || !Number.isFinite(rh)) return null;
  if (t < 26) return t;
  const f = t * 9 / 5 + 32;
  const hi = -42.379 + 2.04901523 * f + 10.14333127 * rh
    - 0.22475541 * f * rh - 0.00683783 * f * f
    - 0.05481717 * rh * rh + 0.00122874 * f * f * rh
    + 0.00085282 * f * rh * rh - 0.00000199 * f * f * rh * rh;
  return (hi - 32) * 5 / 9;
}

async function loadRealtime(stationId) {
  realtimePanel.hidden = false;
  document.querySelector("#realtime-station").textContent = `WMO ${stationId} 实时状态`;
  document.querySelector("#realtime-time").textContent = "正在读取……";
  try {
    const response = await fetch(`/api/v1/observations/realtime/${stationId}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
    document.querySelector("#realtime-temperature").textContent = formatValue(data.temperature_c, 1, " °C");
    document.querySelector("#realtime-humidity").textContent = formatValue(data.relative_humidity_pct, 0, "%");
    document.querySelector("#realtime-pressure").textContent = formatValue(data.station_pressure_hpa, 1, " hPa");
    document.querySelector("#realtime-wind").textContent = Number.isFinite(data.wind_speed_ms)
      ? `${windDirectionName(data.wind_direction_deg)} ${formatValue(data.wind_speed_ms, 1, " m/s")}` : "—";
    document.querySelector("#realtime-rain").textContent = formatValue(data.precipitation_1h_mm, 1, " mm");
    document.querySelector("#realtime-visibility").textContent = formatValue(data.visibility_km, 1, " km");
    document.querySelector("#realtime-time").textContent = data.observed_at
      ? `${new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Shanghai" }).format(new Date(data.observed_at))} 北京时间`
      : "各要素更新时间不同";
    document.querySelector("#realtime-note").textContent = "实时状态来源：q-weather 实时观测";
  } catch (error) {
    document.querySelector("#realtime-time").textContent = "读取失败";
    document.querySelector("#realtime-note").textContent = `实时状态暂不可用：${error.message}`;
  }
}

function renderObservationChartDeprecated(series) {
  const started = performance.now();
  const points = [...(series.observations || [])].sort((a, b) => new Date(a.observed_at) - new Date(b.observed_at));
  if (!points.length) return null;
  points.forEach((point) => {
    point.apparent_temperature_c = apparentTemperature(point.temperature_c, point.relative_humidity_pct);
  });
  chart.replaceChildren(svg("rect", { width: 1200, height: 760, fill: "#fff" }));
  const left = 78;
  const right = 1168;
  const x = (index) => left + index / Math.max(points.length - 1, 1) * (right - left);
  const panels = { temperature: [94, 274], pressure: [320, 405], rain: [450, 515], wind: [562, 635], visibility: [680, 724] };
  chart.append(svg("text", { x: left, y: 27, fill: "#253744", "font-size": 20, "font-weight": 700 }, `${series.station_name} · WMO ${series.station_id} · 24H OBSERVATION`));
  chart.append(svg("text", { x: left, y: 48, fill: "#6f777a", "font-size": 10.5 }, `${series.latitude.toFixed(2)}°N  ${series.longitude.toFixed(2)}°E  ·  ${series.observation_date}  ·  ${points.length} hourly records`));
  chart.append(svg("text", { x: right, y: 27, fill: "#126e68", "text-anchor": "end", "font-size": 11, "font-weight": 700 }, "@CloudyLake"));

  points.forEach((point, index) => {
    const hour = new Date(point.observed_at).getHours();
    const major = hour % 6 === 0;
    chart.append(svg("line", { x1: x(index), x2: x(index), y1: 76, y2: panels.visibility[1], stroke: major ? "#d1d4d2" : "#eceeec", "stroke-width": major ? 1 : 0.7, "stroke-dasharray": major ? "0" : "2 5" }));
    if (hour % 3 === 0 || index === points.length - 1) {
      chart.append(svg("text", { x: x(index), y: 746, fill: "#5d696e", "text-anchor": "middle", "font-size": 9 }, new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", hour12: false, timeZone: "Asia/Shanghai" }).format(new Date(point.observed_at))));
    }
  });

  const temperatureValues = ["temperature_c", "dewpoint_c", "apparent_temperature_c"].flatMap((key) => finiteValues(points, key));
  const [tempMin, tempMax] = paddedExtent(temperatureValues);
  const yTemp = (value) => panels.temperature[1] - (value - tempMin) / (tempMax - tempMin) * (panels.temperature[1] - panels.temperature[0]);
  const yRh = (value) => panels.temperature[1] - Number(value) / 100 * (panels.temperature[1] - panels.temperature[0]);
  drawPanelGrid("TEMPERATURE / DEW POINT / RH", panels.temperature, tempMin, tempMax, yTemp, "°C", left, right);
  const temperatureLines = [
    ["temperature_c", "#df2727", 3, ""],
    ["dewpoint_c", "#197d70", 2.7, ""],
    ["apparent_temperature_c", "#d59b20", 2, "5 4"],
    ["relative_humidity_pct", "#3d93b8", 1.6, "3 4", yRh],
  ];
  temperatureLines.forEach(([key, colour, width, dash, customY]) => chart.append(svg("path", { d: linePath(points, key, x, customY || yTemp), fill: "none", stroke: colour, "stroke-width": width, "stroke-dasharray": dash })));

  const [pressureMin, pressureMax] = paddedExtent(finiteValues(points, "station_pressure_hpa"), 0.2);
  const yPressure = (value) => panels.pressure[1] - (value - pressureMin) / (pressureMax - pressureMin) * (panels.pressure[1] - panels.pressure[0]);
  drawPanelGrid("STATION PRESSURE", panels.pressure, pressureMin, pressureMax, yPressure, " hPa", left, right, 2);
  chart.append(svg("path", { d: linePath(points, "station_pressure_hpa", x, yPressure), fill: "none", stroke: "#2563a9", "stroke-width": 2.5 }));

  chart.append(svg("text", { x: left, y: panels.rain[0] - 14, fill: "#253744", "font-size": 12, "font-weight": 700 }, "HOURLY PRECIPITATION"));
  const rainMax = Math.max(...finiteValues(points, "precipitation_1h_mm"), 0.1);
  const barWidth = Math.max((right - left) / points.length - 3, 4);
  points.forEach((point, index) => {
    const value = Number(point.precipitation_1h_mm);
    if (!Number.isFinite(value) || value <= 0) return;
    const height = value / rainMax * (panels.rain[1] - panels.rain[0]);
    chart.append(svg("rect", { x: x(index) - barWidth / 2, y: panels.rain[1] - height, width: barWidth, height, fill: "#f2c94c", opacity: 0.8 }));
  });

  const windValues = [...finiteValues(points, "wind_speed_ms"), ...finiteValues(points, "gust_speed_ms")];
  const [, windMax] = paddedExtent(windValues, 0.16);
  const yWind = (value) => panels.wind[1] - Number(value) / windMax * (panels.wind[1] - panels.wind[0]);
  drawPanelGrid("WIND / GUST", panels.wind, 0, windMax, yWind, " m/s", left, right, 2);
  chart.append(svg("path", { d: linePath(points, "wind_speed_ms", x, yWind), fill: "none", stroke: "#126e68", "stroke-width": 2.3 }));
  chart.append(svg("path", { d: linePath(points, "gust_speed_ms", x, yWind), fill: "none", stroke: "#f2b82d", "stroke-width": 2, "stroke-dasharray": "4 4" }));
  points.forEach((point, index) => {
    if (index % 3 !== 0) return;
    chart.append(svg("text", { x: x(index), y: panels.wind[0] + 13, fill: "#536268", "font-size": 8, "text-anchor": "middle" }, compass(point.wind_direction_deg)));
  });

  const [, visibilityMax] = paddedExtent(finiteValues(points, "visibility_km"), 0.08);
  const yVisibility = (value) => panels.visibility[1] - Number(value) / visibilityMax * (panels.visibility[1] - panels.visibility[0]);
  drawPanelGrid("VISIBILITY", panels.visibility, 0, visibilityMax, yVisibility, " km", left, right, 1);
  chart.append(svg("path", { d: linePath(points, "visibility_km", x, yVisibility), fill: "none", stroke: "#5a7fa3", "stroke-width": 2.2 }));
  drawChartLegend(left, 69);
  addChartInspection(points, x, panels);
  return performance.now() - started;
}

function drawPanelGrid(title, panel, minimum, maximum, y, suffix, left, right, divisions = 3) {
  chart.append(svg("text", { x: left, y: panel[0] - 14, fill: "#253744", "font-size": 12, "font-weight": 700 }, title));
  for (let index = 0; index <= divisions; index += 1) {
    const value = minimum + (maximum - minimum) * index / divisions;
    const position = y(value);
    chart.append(svg("line", { x1: left, x2: right, y1: position, y2: position, stroke: "#e7e9e6", "stroke-width": 0.8 }));
    chart.append(svg("text", { x: left - 8, y: position + 3, fill: "#687479", "text-anchor": "end", "font-size": 8.5 }, `${value.toFixed(divisions === 1 ? 0 : 1)}${suffix}`));
  }
}

function drawChartLegend(left, y) {
  const entries = [["#df2727", "Temperature"], ["#197d70", "Dew point"], ["#d59b20", "Feels like"], ["#3d93b8", "RH"], ["#2563a9", "Pressure"], ["#f2c94c", "Rain"], ["#126e68", "Wind"]];
  entries.forEach(([colour, label], index) => {
    const offset = left + index * 112;
    chart.append(svg("line", { x1: offset, x2: offset + 16, y1: y, y2: y, stroke: colour, "stroke-width": 3 }));
    chart.append(svg("text", { x: offset + 21, y: y + 3, fill: "#5d696e", "font-size": 8.5 }, label));
  });
}

function addChartInspection(points, x, panels) {
  const group = svg("g", { visibility: "hidden" });
  const line = svg("line", { y1: 76, y2: panels.visibility[1], stroke: "#245f91", "stroke-width": 1, "stroke-dasharray": "4 4" });
  const box = svg("rect", { width: 205, height: 64, rx: 4, fill: "#fff", stroke: "#8aa3aa", opacity: 0.96 });
  const labels = [0, 1, 2].map((index) => svg("text", { "font-size": index ? 9.5 : 10.5, fill: index ? "#536268" : "#253744", "font-weight": index ? 500 : 700 }));
  group.append(line, box, ...labels);
  chart.append(group);
  const overlay = svg("rect", { x: 60, y: 74, width: 1120, height: 656, fill: "transparent", cursor: "crosshair" });
  const inspect = (event) => {
    const point = chart.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(chart.getScreenCTM().inverse());
    const index = Math.max(0, Math.min(points.length - 1, Math.round((local.x - 78) / (1168 - 78) * (points.length - 1))));
    const item = points[index];
    const px = x(index);
    const boxX = px > 940 ? px - 214 : px + 9;
    line.setAttribute("x1", px); line.setAttribute("x2", px);
    box.setAttribute("x", boxX); box.setAttribute("y", 80);
    labels[0].setAttribute("x", boxX + 10); labels[0].setAttribute("y", 97);
    labels[0].textContent = new Date(item.observed_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
    labels[1].setAttribute("x", boxX + 10); labels[1].setAttribute("y", 116);
    labels[1].textContent = `T ${formatValue(item.temperature_c, 1, "°C")} · Td ${formatValue(item.dewpoint_c, 1, "°C")} · RH ${formatValue(item.relative_humidity_pct, 0, "%")}`;
    labels[2].setAttribute("x", boxX + 10); labels[2].setAttribute("y", 135);
    labels[2].textContent = `P ${formatValue(item.station_pressure_hpa, 1, " hPa")} · ${compass(item.wind_direction_deg)} ${formatValue(item.wind_speed_ms, 1, " m/s")}`;
    group.setAttribute("visibility", "visible");
  };
  overlay.addEventListener("pointerenter", inspect);
  overlay.addEventListener("pointermove", inspect);
  overlay.addEventListener("pointerdown", inspect);
  overlay.addEventListener("pointerleave", () => group.setAttribute("visibility", "hidden"));
  chart.append(overlay);
}

function renderObservationChart(series) {
  const points = [...(series.observations || [])]
    .sort((left, right) => new Date(left.observed_at) - new Date(right.observed_at))
    .map((point) => ({
      time: point.observed_at,
      temperature: point.temperature_c,
      dewpoint: point.dewpoint_c,
      apparent: apparentTemperature(point.temperature_c, point.relative_humidity_pct),
      humidity: point.relative_humidity_pct,
      pressure: point.station_pressure_hpa,
      seaLevelPressure: null,
      precipitation: point.precipitation_1h_mm,
      windSpeed: point.wind_speed_ms,
      windDirection: point.wind_direction_deg,
    }));
  const latest = points.at(-1);
  return window.CloudyLakeWeatherSeriesRenderer.render(chart, {
    title: `${series.station_name}站(#${series.station_id})24h实况序列`,
    locationLine: `${series.latitude.toFixed(2)}°N  ${series.longitude.toFixed(2)}°E`,
    timeLine: latest ? `查询时次: ${timeLabelForHeader(latest.time)}` : "",
    points,
    includeDateLabels: false,
  });
}

function timeLabelForHeader(value) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
    timeZone: "Asia/Shanghai", timeZoneName: "short",
  }).format(date);
}

async function loadObservationSeries(station, mode) {
  resultSection.hidden = false;
  resultState.hidden = false;
  resultState.className = "station-image-state";
  resultState.textContent = "正在读取逐小时观测……";
  chartWrap.hidden = true;
  downloadButton.hidden = true;
  const query = new URLSearchParams({ mode });
  if (mode === "history") query.set("date", dateInput.value);
  resultTitle.textContent = mode === "past24h" ? `${station.display_name} · WMO ${station.wmo_id} · 过去 24h` : `${station.display_name} · WMO ${station.wmo_id} · ${dateInput.value}`;
  try {
    const response = await fetch(`/api/v1/observations/series/${station.wmo_id}?${query}`);
    const series = await response.json();
    if (!response.ok) throw new Error(series.detail ?? `HTTP ${response.status}`);
    latestSeries = series;
    renderObservationChart(series);
    const firstTime = series.observations[0]?.observed_at
      ? timeLabelForHeader(series.observations[0].observed_at)
      : "—";
    const lastObservation = series.observations[series.observations.length - 1];
    const lastTime = lastObservation?.observed_at
      ? timeLabelForHeader(lastObservation.observed_at)
      : "—";
    resultSource.innerHTML = `资料来源：<a href="${series.source_url}" target="_blank" rel="noopener">q-weather 逐小时观测</a> · ${series.observations.length} 个时次 · ${firstTime}—${lastTime}`;
    resultState.hidden = true;
    chartWrap.hidden = false;
    downloadButton.hidden = false;
  } catch (error) {
    resultState.className = "station-image-state station-image-state--error";
    resultState.textContent = error.message;
  }
}

async function resolveStation(query) {
  const response = await fetch(`/api/v1/stations/resolve?q=${encodeURIComponent(query)}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
  return data;
}

async function updateStationSuggestions() {
  const query = stationInput.value.trim();
  if (!query) { stationOptions.replaceChildren(); return; }
  try {
    const response = await fetch(`/api/v1/stations/search?q=${encodeURIComponent(query)}&limit=8`);
    if (!response.ok) return;
    const data = await response.json();
    stationOptions.replaceChildren(...data.stations.map((station) => {
      const option = document.createElement("option");
      option.value = station.display_name;
      option.label = `${station.wmo_id} · ${station.province}`;
      return option;
    }));
  } catch {}
}

function coordinatePairs(value, output = []) {
  if (Array.isArray(value) && value.length >= 2 && Number.isFinite(value[0]) && Number.isFinite(value[1])) output.push(value);
  else if (Array.isArray(value)) value.forEach((item) => coordinatePairs(item, output));
  return output;
}

function geometryPath(geometry, project) {
  if (!geometry) return "";
  const rings = geometry.type === "Polygon" ? geometry.coordinates : geometry.type === "MultiPolygon" ? geometry.coordinates.flat() : [];
  return rings.map((ring) => ring.map((pair, index) => `${index ? "L" : "M"}${project(pair[0], pair[1]).join(",")}`).join(" ") + " Z").join(" ");
}

async function loadRegion(region) {
  regionStatus.textContent = `正在读取${region}站点……`;
  regionTabs.querySelectorAll("button").forEach((button) => button.classList.toggle("is-active", button.dataset.region === region));
  try {
    const response = await fetch(`/api/v1/stations/region/${encodeURIComponent(region)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail ?? `HTTP ${response.status}`);
    regionMap.replaceChildren(svg("rect", { width: 960, height: 560, fill: "#fbfdfc" }));
    const { west, east, south, north } = data.bounds;
    const middleLatitude = (south + north) / 2;
    const middleLongitude = (west + east) / 2;
    const longitudeScale = Math.cos(middleLatitude * Math.PI / 180);
    const scale = Math.min(880 / ((east - west) * longitudeScale), 480 / (north - south));
    const project = (longitude, latitude) => [
      480 + (longitude - middleLongitude) * longitudeScale * scale,
      280 - (latitude - middleLatitude) * scale,
    ];
    for (let index = 1; index < 5; index += 1) {
      const longitude = west + index / 5 * (east - west);
      const latitude = south + index / 5 * (north - south);
      const gx = project(longitude, middleLatitude)[0];
      const gy = project(middleLongitude, latitude)[1];
      regionMap.append(svg("line", { x1: gx, x2: gx, y1: 30, y2: 530, class: "region-grid" }), svg("line", { x1: 30, x2: 930, y1: gy, y2: gy, class: "region-grid" }));
    }
    (data.boundaries?.features || []).forEach((feature) => regionMap.append(svg("path", { d: geometryPath(feature.geometry, project), class: "region-boundary" })));
    data.stations.forEach((station) => {
      const [cx, cy] = project(station.longitude, station.latitude);
      const group = svg("g", { class: "region-station", tabindex: 0, role: "button", "aria-label": `${station.display_name} ${station.wmo_id}` });
      group.append(svg("circle", { cx, cy, r: 7, class: "region-station-hit" }), svg("circle", { cx, cy, r: 2.8, class: "region-station-dot" }), svg("title", {}, `${station.display_name} · ${station.wmo_id}`));
      const select = () => { stationInput.value = station.display_name; queryForm.requestSubmit(); };
      group.addEventListener("click", select);
      group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") select(); });
      regionMap.append(group);
    });
    regionStatus.textContent = `${region} · ${data.provinces.join("、")} · ${data.stations.length} 站`;
  } catch (error) {
    regionStatus.textContent = `站点地图读取失败：${error.message}`;
  }
}

async function exportPng() {
  if (!latestSeries) return;
  downloadButton.disabled = true;
  try {
    await document.fonts.ready;
    const source = new XMLSerializer().serializeToString(chart);
    const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
    const canvas = document.createElement("canvas");
    canvas.width = 2400; canvas.height = 1520;
    const context = canvas.getContext("2d");
    context.fillStyle = "#fff"; context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    const png = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    const pngUrl = URL.createObjectURL(png);
    const anchor = document.createElement("a");
    anchor.href = pngUrl; anchor.download = `${latestSeries.station_id}_${latestSeries.observation_date}_observations.png`; anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(pngUrl), 1000);
  } finally {
    downloadButton.disabled = false;
  }
}

queryForm.addEventListener("change", (event) => { if (event.target.name === "mode") updateMode(); });
queryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const station = await resolveStation(stationInput.value.trim());
    stationInput.setCustomValidity("");
    queryForm.after(resultSection);
    queryForm.after(realtimePanel);
    await Promise.all([loadRealtime(station.wmo_id), loadObservationSeries(station, selectedMode())]);
  } catch (error) {
    stationInput.setCustomValidity(error.message); stationInput.reportValidity();
    window.setTimeout(() => stationInput.setCustomValidity(""), 2200);
  }
});
stationInput.addEventListener("input", () => { window.clearTimeout(stationSearchTimer); stationSearchTimer = window.setTimeout(updateStationSuggestions, 180); });
downloadButton.addEventListener("click", exportPng);
REGIONS.forEach((region) => {
  const button = document.createElement("button");
  button.type = "button"; button.dataset.region = region; button.textContent = region;
  button.addEventListener("click", () => loadRegion(region));
  regionTabs.append(button);
});
dateInput.max = localIsoDate(new Date());
dateInput.value = dateInput.max;
updateMode();
loadRegion("华东");
const initialQuery = new URLSearchParams(window.location.search);
if (initialQuery.get("station")) {
  stationInput.value = initialQuery.get("station");
  if (initialQuery.get("mode") === "history" && initialQuery.get("date")) {
    queryForm.elements.mode.value = "history";
    dateInput.value = initialQuery.get("date");
    updateMode();
  }
  window.setTimeout(() => queryForm.requestSubmit(), 0);
}
const initialParameters = new URLSearchParams(window.location.search);
const initialStation = initialParameters.get("station");
if (initialStation) {
  stationInput.value = initialStation;
  const initialMode = initialParameters.get("mode");
  if (initialMode === "history") {
    queryForm.elements.mode.value = "history";
    dateInput.value = initialParameters.get("date") || dateInput.value;
    updateMode();
  }
  queryForm.requestSubmit();
}
