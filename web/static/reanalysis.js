const form = document.querySelector("#reanalysis-form");
const dateInput = document.querySelector("#reanalysis-date");
const hourInput = document.querySelector("#reanalysis-hour");
const fieldInput = document.querySelector("#reanalysis-field");
const levelInput = document.querySelector("#reanalysis-level");
const levelWrap = document.querySelector("#reanalysis-level-wrap");
const westInput = document.querySelector("#reanalysis-west");
const eastInput = document.querySelector("#reanalysis-east");
const southInput = document.querySelector("#reanalysis-south");
const northInput = document.querySelector("#reanalysis-north");
const areaLabel = document.querySelector("#reanalysis-area-label");
const status = document.querySelector("#reanalysis-status");
const resultSection = document.querySelector("#reanalysis-result");
const resultTitle = document.querySelector("#reanalysis-result-title");
const resultMeta = document.querySelector("#reanalysis-result-meta");
const plot = document.querySelector("#reanalysis-plot");

const pressureFields = new Set(["temperature", "relative_humidity", "geopotential_height", "wind_speed"]);
let selectionMap = null;
let selectionRectangle = null;
const GRID_STEP = 0.25;
const MAX_LONGITUDE_SPAN = 120;
const MAX_LATITUDE_SPAN = 75;

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function adaptBounds(west, east, south, north) {
  if (![west, east, south, north].every(Number.isFinite)) return null;
  let longitudeSpan = east - west;
  if (longitudeSpan <= 0) longitudeSpan = ((longitudeSpan % 360) + 360) % 360;
  if (longitudeSpan <= 0 || longitudeSpan > 360) longitudeSpan = 360;
  longitudeSpan = clamp(longitudeSpan, 0.5, MAX_LONGITUDE_SPAN);
  let longitudeCentre = ((west + (east - west > 0 ? (east - west) : longitudeSpan) / 2 + 180) % 360 + 360) % 360 - 180;
  longitudeCentre = clamp(longitudeCentre, -180 + longitudeSpan / 2, 180 - longitudeSpan / 2);

  if (north < south) [south, north] = [north, south];
  let latitudeSpan = clamp(north - south, 0.5, MAX_LATITUDE_SPAN);
  let latitudeCentre = clamp((south + north) / 2, -90 + latitudeSpan / 2, 90 - latitudeSpan / 2);
  let fitted = {
    west: Math.floor((longitudeCentre - longitudeSpan / 2) / GRID_STEP) * GRID_STEP,
    east: Math.ceil((longitudeCentre + longitudeSpan / 2) / GRID_STEP) * GRID_STEP,
    south: Math.floor((latitudeCentre - latitudeSpan / 2) / GRID_STEP) * GRID_STEP,
    north: Math.ceil((latitudeCentre + latitudeSpan / 2) / GRID_STEP) * GRID_STEP,
  };
  if (fitted.east - fitted.west > MAX_LONGITUDE_SPAN) fitted.east = fitted.west + MAX_LONGITUDE_SPAN;
  if (fitted.north - fitted.south > MAX_LATITUDE_SPAN) fitted.north = fitted.south + MAX_LATITUDE_SPAN;
  if (fitted.east > 180) { fitted.west -= fitted.east - 180; fitted.east = 180; }
  if (fitted.west < -180) { fitted.east += -180 - fitted.west; fitted.west = -180; }
  if (fitted.north > 90) { fitted.south -= fitted.north - 90; fitted.north = 90; }
  if (fitted.south < -90) { fitted.north += -90 - fitted.south; fitted.south = -90; }
  return fitted;
}

function writeBounds(bounds) {
  westInput.value = bounds.west.toFixed(2);
  eastInput.value = bounds.east.toFixed(2);
  southInput.value = bounds.south.toFixed(2);
  northInput.value = bounds.north.toFixed(2);
  selectionRectangle?.setBounds([[bounds.south, bounds.west], [bounds.north, bounds.east]]);
  areaLabel.textContent = `${westInput.value}—${eastInput.value}°E · ${southInput.value}—${northInput.value}°N`;
}

for (let hour = 0; hour < 24; hour += 1) {
  const option = document.createElement("option");
  option.value = String(hour);
  option.textContent = `${String(hour).padStart(2, "0")}:00`;
  if (hour === 0) option.selected = true;
  hourInput.append(option);
}
const initialDate = new Date(Date.now() - 7 * 86400_000);
dateInput.value = initialDate.toISOString().slice(0, 10);
dateInput.max = new Date(Date.now() - 5 * 86400_000).toISOString().slice(0, 10);

function initializeMap() {
  if (!window.L) return;
  selectionMap = window.L.map("reanalysis-map", {
    minZoom: 2,
    maxZoom: 9,
    scrollWheelZoom: true,
    touchZoom: true,
    zoomSnap: 0.25,
    wheelPxPerZoomLevel: 130,
  });
  window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>',
  }).addTo(selectionMap);
  selectionMap.fitBounds([[15, 70], [60, 145]], { padding: [8, 8] });
  selectionRectangle = window.L.rectangle([[15, 70], [60, 145]], {
    color: "#126e68",
    weight: 2,
    fillColor: "#f2c94c",
    fillOpacity: 0.08,
  }).addTo(selectionMap);
  selectionMap.on("moveend", updateBoundsFromMap);
  window.setTimeout(updateBoundsFromMap, 0);
}

function updateBoundsFromMap() {
  if (!selectionMap) return;
  const bounds = selectionMap.getBounds();
  const fitted = adaptBounds(bounds.getWest(), bounds.getEast(), bounds.getSouth(), bounds.getNorth());
  if (fitted) writeBounds(fitted);
}

function updateMapFromBounds() {
  const values = [westInput, eastInput, southInput, northInput].map((input) => Number(input.value));
  if (!selectionMap || !values.every(Number.isFinite)) return;
  const fitted = adaptBounds(...values);
  if (!fitted) return;
  writeBounds(fitted);
  selectionMap.fitBounds([[fitted.south, fitted.west], [fitted.north, fitted.east]], { animate: false, padding: [0, 0] });
}

[westInput, eastInput, southInput, northInput].forEach((input) => input.addEventListener("change", updateMapFromBounds));
fieldInput.addEventListener("change", () => { levelWrap.hidden = !pressureFields.has(fieldInput.value); });

async function pollJob(jobId) {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const response = await fetch(`/api/v1/reanalysis/jobs/${encodeURIComponent(jobId)}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail ?? `HTTP ${response.status}`);
    if (payload.status === "complete") return payload.result;
    if (payload.status === "failed") throw new Error(payload.detail ?? "ERA5 查询失败");
    status.textContent = payload.status === "queued"
      ? "查询已排队，正在等待资料服务……"
      : "CDS 正在准备所选历史场；小范围通常更快，请保持页面打开……";
    await new Promise((resolve) => window.setTimeout(resolve, 3000));
  }
  throw new Error("查询等待时间过长，请稍后重试或缩小范围");
}

function renderField(result) {
  const titleLevel = result.pressure_hpa ? `${result.pressure_hpa} hPa ` : "";
  resultTitle.textContent = `${titleLevel}${result.field_label}`;
  resultMeta.textContent = `${result.valid_at.slice(0, 16).replace("T", " ")} UTC · ${result.minimum}—${result.maximum} ${result.unit}`;
  const palette = [
    [0, "#225ea8"], [0.22, "#5ba3c7"], [0.44, "#d8edf0"],
    [0.58, "#fff4ad"], [0.76, "#f2c94c"], [1, "#126e68"],
  ];
  const longitudeSpan = Math.max(0.25, result.longitude.at(-1) - result.longitude[0]);
  const latitudeSpan = Math.max(0.25, result.latitude.at(-1) - result.latitude[0]);
  const meanLatitude = (result.latitude.at(-1) + result.latitude[0]) / 2;
  const geographicRatio = longitudeSpan * Math.max(0.2, Math.cos(meanLatitude * Math.PI / 180)) / latitudeSpan;
  plot.style.height = `${Math.round(clamp(plot.clientWidth / Math.max(0.7, geographicRatio) + 110, 430, 760))}px`;
  window.Plotly.react(plot, [{
    type: "contour",
    x: result.longitude,
    y: result.latitude,
    z: result.values,
    colorscale: palette,
    contours: { coloring: "heatmap", showlabels: true, labelfont: { size: 11, color: "#20343e" } },
    line: { width: 0.65, color: "rgba(26,54,66,.54)", smoothing: 0.85 },
    colorbar: { title: { text: result.unit }, thickness: 15, outlinewidth: 1, len: 0.82 },
    hovertemplate: "Lon %{x:.2f}°<br>Lat %{y:.2f}°<br>%{z:.2f} " + result.unit + "<extra></extra>",
  }], {
    margin: { l: 58, r: 72, t: 38, b: 52 },
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#ffffff",
    xaxis: { title: "Longitude", gridcolor: "#e5eceb", zeroline: false },
    yaxis: { title: "Latitude", gridcolor: "#e5eceb", zeroline: false, scaleanchor: "x", scaleratio: 1 },
    annotations: [{ text: "@CloudyLake", x: 1, y: 1.07, xref: "paper", yref: "paper", showarrow: false, xanchor: "right", font: { size: 12, color: "#263943" } }],
    dragmode: "zoom",
  }, {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
    toImageButtonOptions: { format: "png", filename: `CloudyLake_ERA5_${result.field_id}_${result.valid_at.slice(0, 13).replaceAll(/[-T:]/g, "")}`, scale: 2 },
  });
  resultSection.hidden = false;
  status.textContent = "历史场已完成；可悬停读值，使用图内工具继续框选放大或导出。";
  resultSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  resultSection.hidden = true;
  status.textContent = "正在提交 ERA5 区域查询……";
  try {
    const fitted = adaptBounds(
      Number(westInput.value), Number(eastInput.value),
      Number(southInput.value), Number(northInput.value),
    );
    if (!fitted) throw new Error("请输入有效的经纬度边界");
    const changed = [
      Number(westInput.value) !== fitted.west,
      Number(eastInput.value) !== fitted.east,
      Number(southInput.value) !== fitted.south,
      Number(northInput.value) !== fitted.north,
    ].some(Boolean);
    writeBounds(fitted);
    if (changed) status.textContent = "已自动适配为 ERA5 可查询范围，正在提交……";
    const request = {
      valid_date: dateInput.value,
      hour: Number(hourInput.value),
      field: fieldInput.value,
      pressure_hpa: pressureFields.has(fieldInput.value) ? Number(levelInput.value) : null,
      west: fitted.west, east: fitted.east,
      south: fitted.south, north: fitted.north,
    };
    const response = await fetch("/api/v1/reanalysis/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(request),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail ?? `HTTP ${response.status}`);
    renderField(await pollJob(payload.job_id));
  } catch (error) {
    status.textContent = `历史再分析查询失败：${error.message}`;
  } finally {
    button.disabled = false;
  }
});

initializeMap();
