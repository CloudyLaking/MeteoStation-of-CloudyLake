const forecastForm = document.querySelector("#sounding-forecast-form");
const forecastLocation = document.querySelector("#sounding-location");
const forecastDate = document.querySelector("#sounding-date");
const forecastStep = document.querySelector("#sounding-target-step");
const forecastOptions = document.querySelector("#sounding-location-options");
const forecastStatus = document.querySelector("#sounding-status");
const forecastSection = document.querySelector("#sounding-section");
const forecastTitle = document.querySelector("#sounding-title");
const forecastSource = document.querySelector("#sounding-source");
const reopenProfile = document.querySelector("#open-forecast-profile");
const worldMapElement = document.querySelector("#sounding-world-map");
const worldCoordinate = document.querySelector("#forecast-world-coordinate");

let latestForecast = null;
let worldMap = null;
let worldMarker = null;
let worldStationLayer = null;

function setWorldPoint(latitude, longitude, { move = true, updateInput = true } = {}) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || !worldMap) return;
  if (worldMarker) worldMarker.setLatLng([latitude, longitude]);
  else {
    worldMarker = window.L.circleMarker([latitude, longitude], {
      radius: 6,
      color: "#ffffff",
      weight: 2,
      fillColor: "#126e68",
      fillOpacity: 1,
    }).addTo(worldMap);
  }
  if (move) worldMap.setView([latitude, longitude], Math.max(worldMap.getZoom(), 5));
  if (updateInput) forecastLocation.value = `${latitude.toFixed(4)},${longitude.toFixed(4)}`;
  worldCoordinate.textContent = `已选择 ${latitude.toFixed(4)}°, ${longitude.toFixed(4)}° · 可继续拖动地图重新选点`;
}

function initializeWorldMap() {
  if (!worldMapElement || !window.L) {
    if (worldCoordinate) worldCoordinate.textContent = "世界地图组件暂未加载；仍可直接输入站号或经纬度。";
    return;
  }
  worldMap = window.L.map(worldMapElement, {
    worldCopyJump: true,
    minZoom: 2,
    maxZoom: 8,
    scrollWheelZoom: true,
    // A higher wheel threshold makes trackpad gestures zoom smoothly instead
    // of jumping several levels per scroll tick.
    wheelPxPerZoomLevel: 140,
    zoomSnap: 0.5,
    zoomDelta: 0.5,
    touchZoom: true,
  }).setView([28, 105], 2);
  window.L.control.attribution({ prefix: false }).addAttribution("本地世界站点目录 · 无外部瓦片底图").addTo(worldMap);
  worldMap.on("click", (event) => {
    setWorldPoint(event.latlng.lat, event.latlng.lng, { move: false, updateInput: true });
  });
  setWorldPoint(31.65, 121.75, { move: false, updateInput: false });
  void loadWorldSoundingStations();
}

async function loadWorldSoundingStations() {
  if (!worldMap) return;
  try {
    const response = await fetch("/api/v1/stations/world", {
      headers: { Accept: "application/json" },
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail ?? `HTTP ${response.status}`);
    const renderer = window.L.canvas({ padding: 0.35 });
    worldStationLayer = window.L.layerGroup().addTo(worldMap);
    for (const station of payload.stations ?? []) {
      if (!Number.isFinite(station.latitude) || !Number.isFinite(station.longitude)) continue;
      const marker = window.L.circleMarker(
        [station.latitude, station.longitude],
        {
          renderer,
          radius: 2.7,
          stroke: false,
          fillColor: "#126e68",
          fillOpacity: 0.82,
        },
      );
      marker.bindTooltip(`${station.display_name} · WMO ${station.wmo_id}`, {
        direction: "top",
        offset: [0, -4],
      });
      marker.on("click", (event) => {
        window.L.DomEvent.stopPropagation(event);
        forecastLocation.value = station.wmo_id;
        setWorldPoint(station.latitude, station.longitude, {
          move: false,
          updateInput: false,
        });
        worldCoordinate.textContent = `${station.display_name} · WMO ${station.wmo_id} · 已选择探空站`;
      });
      worldStationLayer.addLayer(marker);
    }
    worldCoordinate.textContent = `全球 ${payload.station_count ?? worldStationLayer.getLayers().length} 个高空站 · 青色圆点可直接选择；空白处可选模式格点`;
  } catch (error) {
    worldCoordinate.textContent = `全球站点目录读取失败：${error.message}；仍可点击地图选取模式格点。`;
  }
}

function selectedModel() {
  return document.querySelector('input[name="model"]:checked')?.value || "ifs";
}

function selectedCycle() {
  return document.querySelector('input[name="cycle"]:checked')?.value || "00";
}

function rebuildSteps() {
  const cadence = selectedModel() === "aifs" ? 6 : 3;
  const previous = Number(forecastStep.value || 24);
  forecastStep.replaceChildren();
  for (let hour = 0; hour <= 144; hour += cadence) {
    const option = document.createElement("option");
    option.value = String(hour);
    option.textContent = hour === 0 ? "分析场 · +0 h" : `+${hour} h`;
    forecastStep.appendChild(option);
  }
  const nearest = Math.round(previous / cadence) * cadence;
  forecastStep.value = String(Math.max(0, Math.min(144, nearest)));
}

function openProfile(payload) {
  if (!payload || !window.CloudyLakeSoundingRenderer) return;
  const validAt = payload.profile.valid_at.slice(0, 16).replace("T", " ");
  const model = payload.model.toUpperCase();
  window.CloudyLakeSoundingRenderer.open({
    profile: payload.profile,
    diagnostics: payload.diagnostics,
    stationName: payload.station_name,
    meta:
      `${payload.requested_location} · ${model} · +${payload.step_hours} h · ` +
      `${validAt} UTC · ${payload.profile.level_count} forecast levels`,
    rawUrl: null,
  });
}

document.querySelectorAll('input[name="model"]').forEach((input) => {
  input.addEventListener("change", rebuildSteps);
});
rebuildSteps();

initLocationSuggest(forecastLocation, forecastOptions, {
  onPick: (item) => {
    if (Number.isFinite(item.latitude) && Number.isFinite(item.longitude)) {
      setWorldPoint(item.latitude, item.longitude, { updateInput: false });
    }
    forecastForm.requestSubmit();
  },
});

forecastLocation.addEventListener("change", async () => {
  const query = forecastLocation.value.trim();
  const coordinate = query.match(/^\s*([+-]?\d+(?:\.\d+)?)\s*[,，]\s*([+-]?\d+(?:\.\d+)?)\s*$/);
  if (coordinate) {
    setWorldPoint(Number(coordinate[1]), Number(coordinate[2]), { updateInput: false });
    return;
  }
  if (!query) return;
  try {
    const response = await fetch(`/api/v1/stations/resolve?q=${encodeURIComponent(query)}`);
    if (!response.ok) return;
    const station = await response.json();
    setWorldPoint(station.latitude, station.longitude, { updateInput: false });
  } catch {}
});

reopenProfile.addEventListener("click", () => openProfile(latestForecast));

forecastForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const location = forecastLocation.value.trim();
  if (!location) {
    forecastStatus.textContent = "请输入国家站号、站名或“纬度,经度”。";
    return;
  }

  const model = selectedModel();
  const cycle = selectedCycle();
  const step = forecastStep.value;
  const query = new URLSearchParams({
    date: forecastDate.value,
    cycle,
    model,
    step,
  });
  forecastStatus.textContent =
    `正在读取 ${model.toUpperCase()} +${step} 小时探空预报……`;
  forecastSection.hidden = true;

  try {
    const response = await fetch(
      `/api/v1/forecast/sounding/${encodeURIComponent(location)}/interactive?${query}`,
    );
    const payload = await response.json();
    if (!response.ok) {
      const detail = payload.detail;
      if (detail && typeof detail === "object" && detail.status === "unavailable") {
        const reason = detail.reason === "stale"
          ? `资料已超过最大允许陈旧时间 ${detail.max_stale_hours} h（当前年龄 ${detail.age_hours} h）`
          : `当前无可用 ${detail.model.toUpperCase()} 预报资料`;
        throw new Error(`${reason}，请稍后重试或切换模式。`);
      }
      throw new Error(detail || `HTTP ${response.status}`);
    }
    latestForecast = payload;
    const validAt = payload.profile.valid_at.slice(0, 16).replace("T", " ");
    const meta = payload.meta || {};
    const ageText = Number.isFinite(Number(meta.data_age_hours))
      ? `资料年龄 ${Number(meta.data_age_hours).toFixed(1)} h`
      : "";
    const degradedText = meta.degraded ? " · 降级资料" : "";
    forecastTitle.textContent =
      `${payload.station_name} · ${model.toUpperCase()} +${payload.step_hours} h`;
    forecastSource.textContent =
      `${validAt} UTC · ${payload.profile.source} · ` +
      `${payload.profile.station_latitude.toFixed(3)}, ` +
      `${payload.profile.station_longitude.toFixed(3)}`;
    forecastSection.hidden = false;
    forecastStatus.textContent = [ageText, degradedText].filter(Boolean).join("，");
    openProfile(payload);
  } catch (error) {
    forecastStatus.textContent = `探空预报读取失败：${error.message}`;
  }
});

const params = new URLSearchParams(window.location.search);
initializeWorldMap();
forecastDate.value = params.get("date") || new Date().toISOString().slice(0, 10);
if (params.get("location")) forecastLocation.value = params.get("location");
if (params.get("model")) {
  const modelInput = document.querySelector(
    `input[name="model"][value="${params.get("model")}"]`,
  );
  if (modelInput) modelInput.checked = true;
}
if (params.get("cycle")) {
  const cycleInput = document.querySelector(
    `input[name="cycle"][value="${params.get("cycle")}"]`,
  );
  if (cycleInput) cycleInput.checked = true;
}
rebuildSteps();
if (params.get("step")) forecastStep.value = params.get("step");
if (params.get("autoload") === "1") {
  forecastForm.requestSubmit();
}
