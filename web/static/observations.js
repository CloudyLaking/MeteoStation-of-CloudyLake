const queryForm = document.querySelector("#station-query-form");
const stationInput = document.querySelector("#surface-station");
const dateInput = document.querySelector("#surface-date");
const dateWrap = document.querySelector("#history-date-wrap");
const realtimePanel = document.querySelector("#realtime-panel");
const imageResult = document.querySelector("#station-image-result");
const imageState = document.querySelector("#station-image-state");
const resultImage = document.querySelector("#station-image");
const downloadLink = document.querySelector("#station-image-download");
const imageTitle = document.querySelector("#station-image-title");
const imageSource = document.querySelector("#station-image-source");
const stationOptions = document.querySelector("#surface-station-options");

let imageObjectUrl = null;
let stationSearchTimer = null;

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

function formatValue(value, digits, suffix) {
  return Number.isFinite(value) ? `${value.toFixed(digits)}${suffix}` : "—";
}

function windDirectionName(degrees) {
  if (!Number.isFinite(degrees)) {
    return "风向缺测";
  }
  const names = [
    "北风", "北偏东北风", "东北风", "东北偏东风",
    "东风", "东南偏东风", "东南风", "南偏东南风",
    "南风", "南偏西南风", "西南风", "西南偏西风",
    "西风", "西北偏西风", "西北风", "西北偏北风",
  ];
  return names[Math.round((degrees % 360) / 22.5) % 16];
}

async function loadRealtime(stationId) {
  realtimePanel.hidden = false;
  document.querySelector("#realtime-station").textContent =
    `WMO ${stationId} 实时状态`;
  document.querySelector("#realtime-time").textContent = "正在读取……";
  try {
    const response = await fetch(`/api/v1/observations/realtime/${stationId}`, {
      headers: { Accept: "application/json" },
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail ?? `HTTP ${response.status}`);
    }
    document.querySelector("#realtime-temperature").textContent =
      formatValue(data.temperature_c, 1, " °C");
    document.querySelector("#realtime-humidity").textContent =
      formatValue(data.relative_humidity_pct, 0, "%");
    document.querySelector("#realtime-pressure").textContent =
      formatValue(data.station_pressure_hpa, 1, " hPa");
    document.querySelector("#realtime-wind").textContent =
      Number.isFinite(data.wind_speed_ms)
        ? `${windDirectionName(data.wind_direction_deg)} ${formatValue(data.wind_speed_ms, 1, " m/s")}`
        : "—";
    document.querySelector("#realtime-rain").textContent =
      formatValue(data.precipitation_1h_mm, 1, " mm");
    document.querySelector("#realtime-visibility").textContent =
      formatValue(data.visibility_km, 1, " km");
    document.querySelector("#realtime-time").textContent = data.observed_at
      ? `${new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "Asia/Shanghai",
      }).format(new Date(data.observed_at))} 北京时间`
      : "各要素更新时间不同";
    document.querySelector("#realtime-note").textContent =
      "实时状态来源：q-weather realtime API";
  } catch (error) {
    document.querySelector("#realtime-time").textContent = "读取失败";
    document.querySelector("#realtime-note").textContent =
      `实时状态暂不可用：${error.message}`;
  }
}

async function loadStaticImage(station, mode) {
  const stationId = station.wmo_id;
  if (imageObjectUrl) {
    URL.revokeObjectURL(imageObjectUrl);
    imageObjectUrl = null;
  }
  imageResult.hidden = false;
  resultImage.hidden = true;
  imageState.hidden = false;
  imageState.className = "station-image-state";
  imageState.textContent = "正在读取原版逐小时资料并生成静态图……";
  downloadLink.hidden = true;

  const query = new URLSearchParams({ station: stationId, mode });
  if (mode === "history") {
    query.set("date", dateInput.value);
  }
  const sourceUrl = `/api/v1/observations/plot?${query.toString()}`;
  imageTitle.textContent = mode === "past24h"
    ? `${station.display_name} · WMO ${stationId} · 过去 24h`
    : `${station.display_name} · WMO ${stationId} · ${dateInput.value}`;
  imageSource.textContent = "数据来源：正在读取 q-weather hourly……";

  try {
    const response = await fetch(sourceUrl, { cache: "no-store" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail ?? `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const source = response.headers.get("X-Observation-Source") ?? "Q-WEATHER-HOURLY";
    const upstreamUrl = response.headers.get("X-Observation-Source-URL");
    const count = response.headers.get("X-Observation-Count") ?? "—";
    imageSource.replaceChildren(
      document.createTextNode("数据来源："),
      Object.assign(document.createElement("a"), {
        href: upstreamUrl ?? "https://q-weather.info/",
        target: "_blank",
        rel: "noopener",
        textContent: source.replace("-", " "),
      }),
      document.createTextNode(` · ${count} 条逐小时记录`),
    );
    imageObjectUrl = URL.createObjectURL(blob);
    resultImage.src = imageObjectUrl;
    resultImage.alt = `${imageTitle.textContent}气象站实况静态图`;
    resultImage.hidden = false;
    imageState.hidden = true;
    downloadLink.href = imageObjectUrl;
    downloadLink.download =
      `${stationId}_${mode === "past24h" ? "past-24h" : dateInput.value}_observations.png`;
    downloadLink.hidden = false;
  } catch (error) {
    imageState.className = "station-image-state station-image-state--error";
    imageState.textContent = error.message;
  }
}

async function resolveStation(query) {
  const response = await fetch(
    `/api/v1/stations/resolve?q=${encodeURIComponent(query)}`,
    { headers: { Accept: "application/json" } },
  );
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail ?? `HTTP ${response.status}`);
  }
  return data;
}

async function updateStationSuggestions() {
  const query = stationInput.value.trim();
  if (!query) {
    stationOptions.replaceChildren();
    return;
  }
  try {
    const response = await fetch(
      `/api/v1/stations/search?q=${encodeURIComponent(query)}&limit=8`,
      { headers: { Accept: "application/json" } },
    );
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    stationOptions.replaceChildren(
      ...data.stations.map((station) => {
        const option = document.createElement("option");
        option.value = station.display_name;
        option.label = `${station.wmo_id} · ${station.province}`;
        return option;
      }),
    );
  } catch (_error) {
    stationOptions.replaceChildren();
  }
}

queryForm.addEventListener("change", (event) => {
  if (event.target.name === "mode") {
    updateMode();
  }
});

queryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const stationQuery = stationInput.value.trim();
  const mode = selectedMode();
  try {
    const station = await resolveStation(stationQuery);
    stationInput.setCustomValidity("");
    await Promise.all([
      loadRealtime(station.wmo_id),
      loadStaticImage(station, mode),
    ]);
  } catch (error) {
    stationInput.setCustomValidity(error.message);
    stationInput.reportValidity();
    window.setTimeout(() => stationInput.setCustomValidity(""), 2200);
  }
});

stationInput.addEventListener("input", () => {
  window.clearTimeout(stationSearchTimer);
  stationSearchTimer = window.setTimeout(updateStationSuggestions, 180);
});

dateInput.max = localIsoDate(new Date());
dateInput.value = dateInput.max;
updateMode();
