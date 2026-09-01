const sourceStrip = document.querySelector("#source-strip");
const stationForm = document.querySelector(".station-form");
const soundingResult = document.querySelector("#sounding-result");
const archiveDate = document.querySelector("#archive-date");
const archiveNote = document.querySelector("#archive-note");
const previousDay = document.querySelector("#previous-day");
const nextDay = document.querySelector("#next-day");
const cycleButtons = document.querySelectorAll("[data-cycle]");
const viewerButtons = document.querySelectorAll("[data-view]");
const profileWorkspace = document.querySelector("#profile-workspace");
const profileWorkspaceMeta = document.querySelector("#profile-workspace-meta");
const profileView = document.querySelector("#profile-view");
const profileChart = document.querySelector("#profile-chart");
const sourceTableWrap = document.querySelector("#source-table-wrap");
const sourceTableBody = document.querySelector("#source-table-body");
const rawDownload = document.querySelector("#raw-download");
const profileClose = document.querySelector("#profile-close");
const levelPressure = document.querySelector("#level-pressure");
const levelHeight = document.querySelector("#level-height");
const levelValues = document.querySelector("#level-values");
const exportButtons = document.querySelectorAll("[data-export]");
const weatherMapButtons = document.querySelectorAll("[data-map-layer]");
const stationDisplayButtons = document.querySelectorAll("[data-station-display]");
const weatherMapImage = document.querySelector("#weather-map-image");
const weatherMapBadge = document.querySelector("#weather-map-badge");
const weatherMapPlaceholder = document.querySelector(".map-placeholder");
const weatherMapStatus = document.querySelector("#weather-map-status");
const weatherMapLayerName = document.querySelector("#weather-map-layer-name");
const weatherMapDescription = document.querySelector("#weather-map-description");
const weatherMapAttribution = document.querySelector("#map-attribution");
const mapSoundingStations = document.querySelector("#map-sounding-stations");
const correctionForm = document.querySelector("#sounding-correction");
const correctionPressure = document.querySelector("#correction-pressure");
const correctionTemperature = document.querySelector("#correction-temperature");
const correctionDewpoint = document.querySelector("#correction-dewpoint");
const correctionTime = document.querySelector("#correction-time");
const correctionRealtime = document.querySelector("#correction-realtime");
const correctionReset = document.querySelector("#correction-reset");
const correctionStatus = document.querySelector("#correction-status");
const soundingStationOptions = document.querySelector("#sounding-station-options");

const SVG_NS = "http://www.w3.org/2000/svg";
const STANDARD_LEVELS = [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100];
const CHART = {
  width: 1400,
  height: 820,
  top: 78,
  bottom: 760,
  plotLeft: 160,
  plotRight: 800,
  humidityLeft: 42,
  humidityRight: 96,
  windLeft: 805,
  windRight: 843,
  barbsLeft: 850,
  barbsRight: 940,
  hodoLeft: 950,
  hodoRight: 1250,
  hodoTop: 78,
  hodoBottom: 390,
  thetaeLeft: 1260,
  thetaeRight: 1382,
  thetaeTop: 78,
  thetaeBottom: 390,
  diagnosticsTop: 404,
  // The diagnostic groups and their favourability key share one framed column.
  diagnosticsBottom: 760,
};

let selectedView = "skewt";
let currentSounding = null;
let chartProjection = null;
let exportFontDataPromise = null;
let weatherMapConfig = null;
let selectedWeatherLayer = "composite";
let selectedStationDisplay = "composite";
let mapStationProfiles = new Map();
let weatherMapPlotBounds = null;
let weatherMapMetadataUrl = null;

const DEFAULT_WEATHER_MAP_PLOT_BOUNDS = {
  left: 0.075,
  right: 0.860,
  bottom: 0.100,
  top: 0.860,
};

const sourceRoleLabels = {
  primary: "探空主源",
  "primary-v1": "地面主源",
  supplement: "补充",
  fallback: "备用",
  "future-primary": "后续主源",
  realtime: "实时交换",
  background: "模式背景",
};

async function loadProjectStatus() {
  try {
    const response = await fetch("/api/v1/status", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    sourceStrip.innerHTML = `
      <span class="source-strip__label">资料链路</span>
      ${data.sources
        .map(
          (source) => `
            <a class="source-chip" href="${escapeHtml(source.url || "#")}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(sourceRoleLabels[source.role] ?? source.role)}">
              ${escapeHtml(source.label)}
            </a>
          `,
        )
        .join("")}
    `;
  } catch (error) {
    sourceStrip.innerHTML = `
      <span class="source-strip__label">资料链路</span>
      <span class="source-chip source-chip--warning">尚未连接</span>
    `;
  }
}

async function loadWeatherMapConfig() {
  try {
    const response = await fetch("/api/v1/weather-maps/config", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    weatherMapConfig = await response.json();
    const baseMap = weatherMapConfig.base_map ?? {};
    const attribution = [baseMap.source, baseMap.service_review_number]
      .filter(Boolean)
      .join(" · ");
    weatherMapAttribution.textContent = attribution
      ? `底图：${attribution}`
      : "";
    renderMapSoundingStations();
    const initialParameters = new URLSearchParams(window.location.search);
    if (!initialParameters.has("date") && !initialParameters.has("cycle")) {
      await selectLatestWeatherMapCycle();
    }
    await loadWeatherMapProduct();
  } catch (error) {
    weatherMapStatus.textContent = "天气图配置读取失败";
    weatherMapDescription.textContent = error.message;
  }
}

async function selectLatestWeatherMapCycle() {
  try {
    const response = await fetch(
      `/api/v1/weather-maps/latest?layer=${encodeURIComponent(selectedWeatherLayer)}`,
      { headers: { Accept: "application/json" } },
    );
    if (!response.ok) return;
    const payload = await response.json();
    const validAt = payload.product?.valid_at;
    if (!validAt) return;
    const instant = new Date(validAt);
    if (Number.isNaN(instant.getTime())) return;
    archiveDate.value = instant.toISOString().slice(0, 10);
    const cycle = String(instant.getUTCHours()).padStart(2, "0");
    cycleButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.cycle === cycle);
    });
    archiveNote.textContent = `${archiveDate.value} ${cycle} 世界时 · 最近完整分析`;
  } catch {
    // Exact-date loading below still provides an explicit status on failure.
  }
}

async function loadWeatherMapProduct() {
  if (!weatherMapConfig || !archiveDate.value) {
    return;
  }
  const layer = weatherMapConfig.layers.find(
    (item) => item.id === selectedWeatherLayer,
  );
  weatherMapLayerName.textContent = layer?.label ?? selectedWeatherLayer;
  weatherMapDescription.textContent =
    layer?.description ?? "等待天气图产品配置。";
  weatherMapStatus.textContent = "正在读取已保存天气图";
  weatherMapBadge.hidden = true;
  weatherMapPlotBounds = null;
  weatherMapMetadataUrl = null;

  const query = new URLSearchParams({
    date: archiveDate.value,
    cycle: selectedCycle(),
    layer: selectedWeatherLayer,
  });
  try {
    const response = await fetch(
      `/api/v1/weather-maps/products?${query.toString()}`,
      { headers: { Accept: "application/json" } },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail ?? `HTTP ${response.status}`);
    }
    const product = data.products[0];
    if (product) {
      void loadWeatherMapGeometry(product.metadata_url);
      weatherMapImage.src = versionedWeatherMapUrl(product);
      weatherMapImage.alt =
        `${layer?.label ?? selectedWeatherLayer} ${archiveDate.value} ${selectedCycle()} UTC`;
      weatherMapImage.hidden = false;
      weatherMapPlaceholder.hidden = true;
      weatherMapStatus.textContent = "已保存天气图";
      mapSoundingStations.hidden = false;
      void refreshMapStationData();
      return;
    }
    if (["composite", "surface", "850", "500", "200"].includes(selectedWeatherLayer)) {
      const previewLayer = selectedWeatherLayer;
      const previewQuery = new URLSearchParams(query);
      previewQuery.set("layer", previewLayer);
      const previewResponse = await fetch(
        `/api/v1/weather-maps/previews?${previewQuery.toString()}`,
        { headers: { Accept: "application/json" } },
      );
      if (previewResponse.ok) {
        const previewData = await previewResponse.json();
        const preview = previewData.previews[0];
        if (preview) {
          void loadWeatherMapGeometry(preview.metadata_url);
          weatherMapImage.src = versionedWeatherMapUrl(preview);
          weatherMapImage.alt =
            `${layer?.label ?? selectedWeatherLayer} ECMWF 天气场开发预览`;
          weatherMapImage.hidden = false;
          weatherMapPlaceholder.hidden = true;
          weatherMapBadge.hidden = true;
          weatherMapStatus.textContent = "ECMWF 天气场开发预览";
          weatherMapDescription.textContent =
            preview.base_map_status === "official-service-preview"
              ? "已合成天地图标准地图服务、国省界、城市与水系注记。"
              : (
                  preview.base_map_status === "official-boundary-preview"
                    ? "已叠加天地图省级行政区与境界数据。"
                    : "当前仅显示 ECMWF 连续场。"
                );
          mapSoundingStations.hidden = false;
          void refreshMapStationData();
          return;
        }
      }
    }
    weatherMapImage.hidden = true;
    mapSoundingStations.hidden = true;
    weatherMapBadge.hidden = true;
    weatherMapPlaceholder.hidden = false;
    weatherMapStatus.textContent = "该时次尚无已保存产品";
    const blockerLabels = {
      "compliant-base-map": "合规标准底图",
      "ecmwf-input": "ECMWF 输入场",
      "cyclone-data-source": "气旋资料源",
    };
    const inputLabels = {
      "ecmwf-surface": "ECMWF 地面场",
      "ecmwf-pressure": "ECMWF 850/500/200 hPa 场",
    };
    const blockers = (data.job?.blockers ?? [])
      .map((item) => blockerLabels[item] ?? item)
      .join("、");
    const missingInputs = (
      data.input_plan?.missing_required_inputs ?? []
    )
      .map((item) => inputLabels[item] ?? item)
      .join("、");
    weatherMapDescription.textContent =
      `${layer?.description ?? ""} 当前尚缺：${missingInputs || blockers || "本时次分析产品"}。`;
  } catch (error) {
    weatherMapImage.hidden = true;
    mapSoundingStations.hidden = true;
    weatherMapBadge.hidden = true;
    weatherMapPlaceholder.hidden = false;
    weatherMapStatus.textContent = "天气图读取失败";
    weatherMapDescription.textContent = error.message;
  }
}

function versionedWeatherMapUrl(product) {
  const url = new URL(product.image_url, window.location.origin);
  if (product.generated_at) url.searchParams.set("v", product.generated_at);
  return `${url.pathname}${url.search}`;
}

async function loadWeatherMapGeometry(metadataUrl) {
  weatherMapMetadataUrl = metadataUrl || null;
  const requestedMetadataUrl = weatherMapMetadataUrl;
  weatherMapPlotBounds = null;
  if (!metadataUrl) {
    updateMapStationPositions();
    return;
  }
  try {
    const response = await fetch(metadataUrl, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const metadata = await response.json();
    if (weatherMapMetadataUrl !== requestedMetadataUrl) {
      return;
    }
    const bounds = metadata?.rendering?.plot_bounds_fraction;
    if (
      [bounds?.left, bounds?.right, bounds?.bottom, bounds?.top]
        .every(Number.isFinite) &&
      bounds.left >= 0 &&
      bounds.right <= 1 &&
      bounds.bottom >= 0 &&
      bounds.top <= 1 &&
      bounds.left < bounds.right &&
      bounds.bottom < bounds.top
    ) {
      weatherMapPlotBounds = bounds;
    }
  } catch (error) {
    if (weatherMapMetadataUrl !== requestedMetadataUrl) {
      return;
    }
    weatherMapPlotBounds = null;
  }
  updateMapStationPositions();
}

function renderMapSoundingStations() {
  if (!mapSoundingStations || !weatherMapConfig) {
    return;
  }
  mapSoundingStations.replaceChildren();
  for (const station of weatherMapConfig.sounding_stations ?? []) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "map-sounding-station";
    button.dataset.stationId = station.wmo_id;
    button.dataset.longitude = String(station.longitude);
    button.dataset.latitude = String(station.latitude);
    button.style.zIndex = String(1000 - Number(station.priority ?? 100));
    button.setAttribute(
      "aria-label",
      `打开${station.name} ${station.wmo_id}探空`,
    );
    button.addEventListener("click", () => {
      stationForm.elements.station.value = station.wmo_id;
      stationForm.requestSubmit();
    });
    mapSoundingStations.append(button);
  }
  updateMapStationPositions();
  updateMapStationLabels();
}

function updateMapStationPositions() {
  if (
    !weatherMapConfig ||
    !weatherMapImage.naturalWidth ||
    weatherMapImage.hidden
  ) {
    return;
  }
  const stage = weatherMapImage.parentElement;
  const stageWidth = stage.clientWidth;
  const stageHeight = stage.clientHeight;
  const imageRatio =
    weatherMapImage.naturalWidth / weatherMapImage.naturalHeight;
  const stageRatio = stageWidth / stageHeight;
  const renderedWidth =
    stageRatio > imageRatio ? stageHeight * imageRatio : stageWidth;
  const renderedHeight =
    stageRatio > imageRatio ? stageHeight : stageWidth / imageRatio;
  const offsetX = (stageWidth - renderedWidth) / 2;
  const offsetY = (stageHeight - renderedHeight) / 2;
  const domain = weatherMapConfig.domain;
  const bounds = weatherMapPlotBounds ?? DEFAULT_WEATHER_MAP_PLOT_BOUNDS;
  const stationModelSize = Math.max(
    12,
    Math.min(36, (renderedWidth / weatherMapImage.naturalWidth) * 68),
  );
  mapSoundingStations.style.setProperty(
    "--station-model-size",
    `${stationModelSize.toFixed(2)}px`,
  );
  for (const button of mapSoundingStations.children) {
    const longitude = Number(button.dataset.longitude);
    const latitude = Number(button.dataset.latitude);
    const longitudeFraction =
      (longitude - domain.west) / (domain.east - domain.west);
    const latitudeFraction =
      (latitude - domain.south) / (domain.north - domain.south);
    const figureX =
      bounds.left + longitudeFraction * (bounds.right - bounds.left);
    const figureY =
      1 - (bounds.bottom + latitudeFraction * (bounds.top - bounds.bottom));
    button.style.left = `${offsetX + renderedWidth * figureX}px`;
    button.style.top = `${offsetY + renderedHeight * figureY}px`;
  }
}

function updateMapStationLabels() {
  for (const button of mapSoundingStations.children) {
    const station = (weatherMapConfig?.sounding_stations ?? []).find(
      (item) => item.wmo_id === button.dataset.stationId,
    );
    const profile = mapStationProfiles.get(button.dataset.stationId);
    const isReady = Boolean(profile?.levels?.length);
    let level = null;
    let levelLabel = "SFC";
    if (profile?.levels?.length) {
      const levels = [...profile.levels].sort(
        (first, second) => second.pressure_hpa - first.pressure_hpa,
      );
      const targetPressure = ["850", "500", "200"].includes(
        selectedWeatherLayer,
      )
        ? Number(selectedWeatherLayer)
        : null;
      level = targetPressure
        ? levels.reduce((nearest, item) =>
            Math.abs(item.pressure_hpa - targetPressure) <
            Math.abs(nearest.pressure_hpa - targetPressure)
              ? item
              : nearest,
          )
        : levels[0];
      levelLabel = targetPressure ? `${targetPressure} hPa` : "surface";
    }
    const formatValue = (value) =>
      Number.isFinite(value) ? String(Math.round(value)) : "—";
    const secondaryValue = ["850", "500", "200"].includes(
      selectedWeatherLayer,
    )
      ? (
          Number.isFinite(level?.geopotential_height_m)
            ? `${Math.round(level.geopotential_height_m / 10)}`
            : "—"
        )
      : formatValue(level?.pressure_hpa);
    const statusColor = isReady ? "#35a85b" : "#e1b42f";
    if (!isReady) {
      button.innerHTML = `
        <svg viewBox="0 0 74 74" aria-hidden="true">
          <circle cx="37" cy="37" r="3.2" fill="${statusColor}"></circle>
        </svg>
      `;
      const detail =
        `${station?.name ?? ""} ${station?.wmo_id ?? button.dataset.stationId}` +
        " · 尚未更新";
      button.title = detail;
      button.setAttribute("aria-label", `${detail}；点击查看探空`);
      continue;
    }
    if (selectedStationDisplay !== "composite") {
      const displayValues = {
        temperature: {
          value: formatValue(level?.temperature_c),
          unit: "°C",
          className: "station-value--temperature",
        },
        dewpoint: {
          value: formatValue(level?.dewpoint_c),
          unit: "°C",
          className: "station-value--dewpoint",
        },
        height: {
          value: secondaryValue,
          unit: ["850", "500", "200"].includes(selectedWeatherLayer) ? "dam" : "hPa",
          className: "station-value--height",
        },
        wind: {
          value: Number.isFinite(level?.wind_speed_ms)
            ? Number(level.wind_speed_ms).toFixed(1)
            : "—",
          unit: "m/s",
          className: "station-value--wind",
        },
      };
      const item = displayValues[selectedStationDisplay];
      button.innerHTML = `
        <svg class="station-value-model ${item.className}" viewBox="0 0 74 74" aria-hidden="true">
          <circle cx="37" cy="54" r="2.5" fill="${statusColor}"></circle>
          <text x="37" y="34" text-anchor="middle" font-size="16" font-weight="800">${item.value}</text>
          <text x="37" y="47" text-anchor="middle" font-size="6.5" font-weight="650">${item.unit}</text>
        </svg>
      `;
      button.title = `${station?.name ?? ""} ${station?.wmo_id ?? button.dataset.stationId} · ${levelLabel} · ${item.value} ${item.unit}`;
      continue;
    }
    const windBarb = weatherStationBarbSvg(
      level?.wind_direction_deg,
      level?.wind_speed_ms,
    );
    button.innerHTML = `
      <svg viewBox="0 0 74 74" aria-hidden="true">
        ${windBarb}
        <circle cx="37" cy="37" r="3.2" fill="${statusColor}"></circle>
        <text class="station-model__temperature" x="29" y="31" text-anchor="end" font-size="10.5" font-weight="700">${formatValue(level?.temperature_c)}</text>
        <text class="station-model__dewpoint" x="29" y="48" text-anchor="end" font-size="10.5" font-weight="700">${formatValue(level?.dewpoint_c)}</text>
        <text class="station-model__secondary" x="45" y="31" font-size="9" font-weight="650">${secondaryValue}</text>
        <text class="station-model__id" x="44" y="48" font-size="7.5" font-weight="550">${escapeHtml(station?.wmo_id ?? button.dataset.stationId)}</text>
      </svg>
    `;
    const statusText = isReady ? "已更新" : "尚未更新";
    const detail =
      `${station?.name ?? ""} ${station?.wmo_id ?? button.dataset.stationId}` +
      ` · ${levelLabel} · ${statusText}` +
      ` · T ${formatValue(level?.temperature_c)}°C` +
      ` · Td ${formatValue(level?.dewpoint_c)}°C` +
      (
        Number.isFinite(level?.geopotential_height_m) &&
        ["850", "500", "200"].includes(selectedWeatherLayer)
          ? ` · H ${Math.round(level.geopotential_height_m / 10)} dagpm`
          : ""
      );
    button.title = detail;
    button.setAttribute("aria-label", `${detail}；点击打开探空`);
  }
}

function weatherStationBarbSvg(directionDegrees, speedMs) {
  if (!Number.isFinite(directionDegrees) || !Number.isFinite(speedMs)) {
    return "";
  }
  const radians = (directionDegrees * Math.PI) / 180;
  const shaftLength = 25;
  const centreX = 37;
  const centreY = 37;
  const unitX = Math.sin(radians);
  const unitY = -Math.cos(radians);
  const perpendicularX = -unitY;
  const perpendicularY = unitX;
  const endX = centreX + unitX * shaftLength;
  const endY = centreY + unitY * shaftLength;
  let remainingKnots = Math.max(0, speedMs * 1.94384);
  let offset = 1;
  const parts = [
    `<line x1="${centreX}" y1="${centreY}" x2="${endX.toFixed(2)}" y2="${endY.toFixed(2)}" stroke="#111" stroke-width="1.7" stroke-linecap="round"></line>`,
  ];
  while (remainingKnots >= 47.5) {
    const baseX = endX - unitX * offset;
    const baseY = endY - unitY * offset;
    const nextX = baseX - unitX * 5;
    const nextY = baseY - unitY * 5;
    parts.push(
      `<polygon points="${baseX.toFixed(2)},${baseY.toFixed(2)} ${(baseX + perpendicularX * 9).toFixed(2)},${(baseY + perpendicularY * 9).toFixed(2)} ${nextX.toFixed(2)},${nextY.toFixed(2)}" fill="#111"></polygon>`,
    );
    remainingKnots -= 50;
    offset += 6;
  }
  while (remainingKnots >= 7.5) {
    const baseX = endX - unitX * offset;
    const baseY = endY - unitY * offset;
    parts.push(
      `<line x1="${baseX.toFixed(2)}" y1="${baseY.toFixed(2)}" x2="${(baseX + perpendicularX * 9).toFixed(2)}" y2="${(baseY + perpendicularY * 9).toFixed(2)}" stroke="#111" stroke-width="1.6"></line>`,
    );
    remainingKnots -= 10;
    offset += 4;
  }
  if (remainingKnots >= 2.5) {
    const baseX = endX - unitX * offset;
    const baseY = endY - unitY * offset;
    parts.push(
      `<line x1="${baseX.toFixed(2)}" y1="${baseY.toFixed(2)}" x2="${(baseX + perpendicularX * 5).toFixed(2)}" y2="${(baseY + perpendicularY * 5).toFixed(2)}" stroke="#111" stroke-width="1.6"></line>`,
    );
  }
  return parts.join("");
}

async function refreshMapStationData() {
  if (!weatherMapConfig) {
    return;
  }
  const query = new URLSearchParams({
    date: archiveDate.value,
    cycle: selectedCycle(),
  });
  mapStationProfiles.clear();
  try {
    const response = await fetch(
      `/api/v1/weather-maps/sounding-stations?${query.toString()}`,
      { headers: { Accept: "application/json" } },
    );
    if (response.ok) {
      const payload = await response.json();
      for (const item of payload.profiles ?? []) {
        mapStationProfiles.set(item.wmo_id, item.profile);
      }
    }
  } catch (error) {
    mapStationProfiles.clear();
  }
  updateMapStationLabels();
}

weatherMapImage?.addEventListener("load", updateMapStationPositions);
window.addEventListener("resize", updateMapStationPositions);

function toLocalIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function selectedCycle() {
  return document.querySelector("[data-cycle].is-active")?.dataset.cycle ?? "00";
}

function updateArchiveNote() {
  archiveNote.textContent = `${archiveDate.value} ${selectedCycle()} 世界时 · 读取已保存产品`;
  nextDay.disabled = archiveDate.value >= archiveDate.max;
  currentSounding = null;
  soundingResult.hidden = true;
  profileWorkspace.hidden = true;
  void loadWeatherMapProduct();
}

function shiftArchiveDate(dayDelta) {
  const selected = new Date(`${archiveDate.value}T12:00:00`);
  selected.setDate(selected.getDate() + dayDelta);
  const nextValue = toLocalIsoDate(selected);
  if (nextValue <= archiveDate.max) {
    archiveDate.value = nextValue;
    updateArchiveNote();
  }
}

stationForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = stationForm.elements.station;
  const stationQuery = input.value.trim();
  let stationId = stationQuery.match(/(?:^|·\s*)(\d{5})$/)?.[1] ?? stationQuery;
  let resolvedStation = null;

  if (!/^\d{5}$/.test(stationId)) {
    try {
      const stationResponse = await fetch(
        `/api/v1/stations/resolve?q=${encodeURIComponent(stationId)}`,
        { headers: { Accept: "application/json" } },
      );
      const stationPayload = await stationResponse.json();
      if (!stationResponse.ok) {
        throw new Error(stationPayload.detail ?? "找不到该探空站");
      }
      resolvedStation = stationPayload;
      stationId = stationPayload.wmo_id;
      input.value = `${stationPayload.display_name} · ${stationId}`;
    } catch (error) {
      input.setCustomValidity(error.message);
      input.reportValidity();
      window.setTimeout(() => input.setCustomValidity(""), 2200);
      return;
    }
  }

  const cycle = selectedCycle();
  const query = new URLSearchParams({
    date: archiveDate.value,
    cycle,
  });

  soundingResult.hidden = false;
  soundingResult.classList.remove("sounding-result--error");
  soundingResult.innerHTML = `
    <span class="sounding-result__label">正在读取探空资料</span>
    <strong>${stationId}</strong>
    <p>正在查询 ${archiveDate.value} ${cycle} 世界时的廓线。</p>
  `;

  try {
    const response = await fetch(
      `/api/v1/soundings/${stationId}?${query.toString()}`,
      { headers: { Accept: "application/json" } },
    );
    const data = await response.json();
    if (!response.ok) {
      throw new Error(
        response.status === 404
          ? "该站本时次资料尚未到达，更新后将自动开放查看。"
          : (data.detail ?? `HTTP ${response.status}`),
      );
    }

    const [diagnosticsResponse, stationResponse] = await Promise.all([
      fetch(
        `/api/v1/soundings/${stationId}/diagnostics?${query.toString()}`,
        { headers: { Accept: "application/json" } },
      ),
      fetch(`/api/v1/stations/resolve?q=${encodeURIComponent(stationId)}`, {
        headers: { Accept: "application/json" },
      }),
    ]);
    const diagnostics = diagnosticsResponse.ok
      ? await diagnosticsResponse.json()
      : null;
    const station = resolvedStation ?? (stationResponse.ok ? await stationResponse.json() : null);

    currentSounding = {
      data,
      stationId,
      cycle,
      query: query.toString(),
      diagnostics,
      corrected: null,
      stationName: station?.display_name ?? `站号 ${stationId}`,
    };
    populateCorrectionFields(data);
    renderSoundingSummary();
    renderSelectedView();
    profileWorkspace.hidden = false;
  } catch (error) {
    profileWorkspace.hidden = true;
    soundingResult.classList.add("sounding-result--error");
    soundingResult.innerHTML = `
      <span class="sounding-result__label">读取失败</span>
      <strong>${stationId}</strong>
      <p>${escapeHtml(error.message)}</p>
    `;
  }
});

let soundingStationSearchTimer = null;
stationForm?.elements.station?.addEventListener("input", () => {
  window.clearTimeout(soundingStationSearchTimer);
  soundingStationSearchTimer = window.setTimeout(async () => {
    if (!soundingStationOptions) return;
    const query = stationForm.elements.station.value.trim();
    if (!query || query.includes(" · ")) {
      soundingStationOptions.hidden = true;
      return;
    }
    try {
      const response = await fetch(
        `/api/v1/stations/search?q=${encodeURIComponent(query)}&limit=10`,
        { headers: { Accept: "application/json" } },
      );
      const payload = await response.json();
      if (!response.ok || !payload.stations?.length) {
        soundingStationOptions.hidden = true;
        return;
      }
      soundingStationOptions.replaceChildren(...payload.stations.map((station) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "station-suggestion";
        button.innerHTML = `<strong>${escapeHtml(station.display_name)}</strong><small>站号 ${escapeHtml(station.wmo_id)} · ${Number(station.latitude).toFixed(2)}, ${Number(station.longitude).toFixed(2)}</small>`;
        button.addEventListener("click", () => {
          stationForm.elements.station.value = station.wmo_id;
          soundingStationOptions.hidden = true;
          stationForm.requestSubmit();
        });
        return button;
      }));
      soundingStationOptions.hidden = false;
    } catch {
      soundingStationOptions.hidden = true;
    }
  }, 160);
});

document.addEventListener("pointerdown", (event) => {
  if (soundingStationOptions && !event.target.closest(".station-form")) {
    soundingStationOptions.hidden = true;
  }
});

function renderSoundingSummary() {
  if (!currentSounding || !soundingResult) {
    return;
  }

  const { cycle } = currentSounding;
  const data = activeProfile();
  const cacheLabel = data.cache_status === "corrected"
    ? "当前会话订正"
    : (data.cache_status === "hit" ? "已收录" : "最新资料");
  const viewNames = {
    skewt: "交互式 Skew‑T",
    stuve: "交互式 Stüve",
    source: "源数据表",
  };
  soundingResult.innerHTML = `
    <span class="sounding-result__label">探空资料 · ${cacheLabel}</span>
    <strong>${escapeHtml(currentSounding.stationName ?? `站号 ${data.station_id}`)} · ${data.station_id} · ${cycle} 世界时</strong>
    <dl>
      <div><dt>垂直层数</dt><dd>${data.level_count}</dd></div>
      <div><dt>地面气压</dt><dd>${formatNumber(data.surface_pressure_hpa, 1)} hPa</dd></div>
      <div><dt>最高层</dt><dd>${formatNumber(data.top_pressure_hpa, 1)} hPa</dd></div>
    </dl>
    <p>已在页面下方打开${viewNames[selectedView]}；来源：${escapeHtml(data.source)}。</p>
  `;
}

function renderSelectedView() {
  if (!currentSounding) {
    return;
  }

  const { stationId, cycle, query } = currentSounding;
  const data = activeProfile();
  const diagnostics = activeDiagnostics();
  const stationName = currentSounding.stationName
    ?? (stationId === "58362" ? "上海宝山" : `站号 ${stationId}`);
  profileWorkspaceMeta.textContent = currentSounding.meta
    ?? `${stationName} · 站号 ${stationId} · ${archiveDate.value} ${cycle} 世界时 · ${data.level_count} 个实测层`;
  if (rawDownload) {
    rawDownload.hidden = !currentSounding.rawUrl && !query;
    rawDownload.href = currentSounding.rawUrl
      ?? `/api/v1/soundings/${stationId}/raw?${query}`;
  }
  exportButtons.forEach((button) => {
    button.disabled = selectedView === "source";
  });

  if (selectedView === "source") {
    profileView.hidden = true;
    sourceTableWrap.hidden = false;
    renderSourceTable(data.levels);
    return;
  }

  profileView.hidden = false;
  sourceTableWrap.hidden = true;
  renderProfileChart(data, selectedView, stationName, diagnostics);
}

function activeProfile() {
  return currentSounding?.corrected?.profile ?? currentSounding?.data ?? null;
}

function activeDiagnostics() {
  return currentSounding?.corrected?.diagnostics
    ?? currentSounding?.diagnostics
    ?? null;
}

function renderProfileChart(profile, mode, stationName, diagnostics) {
  profileChart.replaceChildren();
  const pressureTop = Math.max(100, profile.top_pressure_hpa);
  const pressureBottom = Math.max(1050, profile.surface_pressure_hpa);
  const mainWidth = CHART.plotRight - CHART.plotLeft;
  const mainHeight = CHART.bottom - CHART.top;
  const xMinimum = mode === "skewt" ? -80 : -85;
  const xMaximum = mode === "skewt" ? 112 : 50;

  const yForPressure = (pressure) => {
    const fraction =
      (Math.log(pressure) - Math.log(pressureTop)) /
      (Math.log(pressureBottom) - Math.log(pressureTop));
    return CHART.top + fraction * mainHeight;
  };
  const pressureForY = (y) => {
    const fraction = clamp((y - CHART.top) / mainHeight, 0, 1);
    return Math.exp(
      Math.log(pressureTop) +
        fraction * (Math.log(pressureBottom) - Math.log(pressureTop)),
    );
  };
  const skewTemperature = (temperature, pressure) =>
    mode === "skewt"
      ? temperature + 27 * Math.log(1000 / pressure)
      : temperature;
  const xForTemperature = (temperature, pressure) =>
    CHART.plotLeft +
    ((skewTemperature(temperature, pressure) - xMinimum) /
      (xMaximum - xMinimum)) *
      mainWidth;

  chartProjection = {
    yForPressure,
    pressureForY,
    xForTemperature,
    mode,
  };

  profileChart.setAttribute("aria-label", `${stationName} sounding`);
  appendSvg(
    "desc",
    { id: "profile-chart-description" },
    "Interactive temperature and dew-point profile with humidity and wind-speed bands.",
  );

  const defs = appendSvg("defs");
  const blur = appendSvgTo(defs, "filter", {
    id: "humidity-blur",
    x: "-35%",
    width: "170%",
  });
  appendSvgTo(blur, "feGaussianBlur", { stdDeviation: "6" });
  const plotClip = appendSvgTo(defs, "clipPath", { id: "plot-clip" });
  appendSvgTo(plotClip, "rect", {
    x: CHART.plotLeft,
    y: CHART.top,
    width: mainWidth,
    height: mainHeight,
  });

  appendSvg("rect", {
    x: "0",
    y: "0",
    width: CHART.width,
    height: CHART.height,
    fill: "#ffffff",
  });
  appendSvg(
    "text",
    {
      x: CHART.humidityLeft,
      y: 31,
      fill: "#263943",
      "font-size": "23",
      "font-weight": "700",
    },
    `${stationName} | ${mode === "skewt" ? "Skew-T" : "Stüve"}`,
  );
  appendSvg(
    "text",
    {
      x: CHART.humidityLeft,
      y: 52,
      fill: "#788286",
      "font-size": "12.5",
      "letter-spacing": "0.5",
    },
    `站号 ${profile.station_id}  |  ${formatUtc(profile.valid_at)}  |  ${profile.level_count} 个实测层  |  ${profile.source}`,
  );
  appendSvg(
    "text",
    {
      x: CHART.thetaeRight,
      y: 31,
      fill: "#126e68",
      "font-size": "13",
      "font-weight": "700",
      "text-anchor": "end",
    },
    "@CloudyLake",
  );
  appendSvg("rect", {
    x: CHART.plotLeft,
    y: CHART.top,
    width: mainWidth,
    height: mainHeight,
    fill: "#fffdfb",
    stroke: "#baa997",
    "stroke-width": "1",
  });

  drawPressureLevels(yForPressure, pressureTop, pressureBottom);
  drawTemperatureGrid(mode, xForTemperature, yForPressure, pressureTop, pressureBottom);
  drawFixedReferenceLevels(
    profile.levels,
    yForPressure,
    pressureTop,
    pressureBottom,
  );
  drawHumidityBand(profile.levels, yForPressure, pressureTop, pressureBottom);
  drawWindBand(profile.levels, yForPressure, pressureTop, pressureBottom);
  drawWindBarbs(profile.levels, yForPressure, pressureTop, pressureBottom);
  drawHodograph(profile.levels, diagnostics);
  drawDiagnosticColumn(diagnostics);
  const diagnosticLevels = joinDiagnosticLevels(profile.levels, diagnostics);
  drawThetaE(diagnosticLevels, yForPressure);
  if (diagnostics && diagnosticLevels.length) {
    drawEnergyAreas(
      diagnosticLevels,
      diagnostics,
      xForTemperature,
      yForPressure,
    );
    drawDiagnosticLevel(
      "LCL",
      diagnostics.lcl_pressure_hpa,
      "#a96d2d",
      yForPressure,
      pressureTop,
      pressureBottom,
      0,
    );
    drawDiagnosticLevel(
      "LFC",
      diagnostics.lfc_pressure_hpa,
      "#b65f4b",
      yForPressure,
      pressureTop,
      pressureBottom,
      1,
    );
    drawDiagnosticLevel(
      "EL",
      diagnostics.equilibrium_level_pressure_hpa,
      "#596f9a",
      yForPressure,
      pressureTop,
      pressureBottom,
      2,
    );
    drawDiagnosticLevel(
      "0 °C",
      diagnostics.freezing_level_pressure_hpa,
      "#6d8fa0",
      yForPressure,
      pressureTop,
      pressureBottom,
      3,
    );
  }

  const temperaturePath = profilePath(
    profile.levels,
    "temperature_c",
    xForTemperature,
    yForPressure,
    pressureTop,
    pressureBottom,
  );
  const dewpointPath = profilePath(
    profile.levels,
    "dewpoint_c",
    xForTemperature,
    yForPressure,
    pressureTop,
    pressureBottom,
  );
  appendSvg("path", {
    d: temperaturePath,
    fill: "none",
    stroke: "#df2727",
    "stroke-width": "3.2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "clip-path": "url(#plot-clip)",
  });
  appendSvg("path", {
    d: dewpointPath,
    fill: "none",
    stroke: "#267d70",
    "stroke-width": "3.2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
    "clip-path": "url(#plot-clip)",
  });
  if (diagnosticLevels.length) {
    appendSvg("path", {
      d: diagnosticPath(
        diagnosticLevels,
        "wet_bulb_temperature_c",
        xForTemperature,
        yForPressure,
      ),
      fill: "none",
      stroke: "#3d9fc4",
      "stroke-width": "1.6",
      "stroke-linecap": "round",
      "clip-path": "url(#plot-clip)",
    });
    appendSvg("path", {
      d: diagnosticPath(
        diagnosticLevels,
        "virtual_temperature_c",
        xForTemperature,
        yForPressure,
      ),
      fill: "none",
      stroke: "#8463a6",
      "stroke-width": "1.8",
      "stroke-dasharray": "7 4",
      "stroke-linecap": "round",
      "clip-path": "url(#plot-clip)",
    });
    appendSvg("path", {
      d: diagnosticPath(
        diagnosticLevels,
        "parcel_temperature_c",
        xForTemperature,
        yForPressure,
      ),
      fill: "none",
      stroke: "#d39143",
      "stroke-width": "2",
      "stroke-dasharray": "3 4",
      "stroke-linecap": "round",
      "clip-path": "url(#plot-clip)",
    });
  }

  appendSvg(
    "text",
    {
      x: (CHART.plotLeft + CHART.plotRight) / 2,
      y: CHART.bottom + 42,
      fill: "#647175",
      "font-size": "12.5",
      "text-anchor": "middle",
    },
    "Temperature (°C)",
  );
  appendSvg(
    "text",
    {
      x: (CHART.humidityLeft + CHART.humidityRight) / 2,
      y: 69,
      fill: "#617276",
      "font-size": "12.5",
      "font-weight": "650",
      "text-anchor": "middle",
    },
    "湿度 / 云层参考",
  );
  appendSvg(
    "text",
    {
      x: (CHART.windLeft + CHART.windRight) / 2,
      y: 69,
      fill: "#617276",
      "font-size": "12.5",
      "font-weight": "650",
      "text-anchor": "middle",
    },
    "风速 米/秒",
  );
  appendSvg(
    "text",
    {
      x: (CHART.barbsLeft + CHART.barbsRight) / 2,
      y: 69,
      fill: "#29363c",
      "font-size": "12.5",
      "font-weight": "700",
      "text-anchor": "middle",
    },
    "风羽",
  );
  drawChartLegend();

  const hoverGroup = appendSvg("g", {
    id: "level-hover",
    visibility: "hidden",
    "pointer-events": "none",
    "data-export-exclude": "true",
  });
  appendSvgTo(hoverGroup, "line", {
    id: "level-hover-line",
    x1: CHART.humidityLeft - 8,
    x2: CHART.barbsRight,
    stroke: "#1f5f93",
    "stroke-width": "1",
    "stroke-dasharray": "4 4",
    opacity: "0.72",
  });
  appendSvgTo(hoverGroup, "line", {
    id: "level-hover-vertical",
    y1: CHART.top,
    y2: CHART.bottom,
    stroke: "#1f5f93",
    "stroke-width": "0.8",
    "stroke-dasharray": "2 5",
    opacity: "0.42",
  });
  appendSvgTo(hoverGroup, "circle", {
    id: "level-hover-temperature",
    r: "5",
    fill: "#fff",
    stroke: "#df2727",
    "stroke-width": "2.4",
  });
  appendSvgTo(hoverGroup, "circle", {
    id: "level-hover-virtual",
    r: "3.7",
    fill: "#fff",
    stroke: "#8463a6",
    "stroke-width": "1.8",
  });
  appendSvgTo(hoverGroup, "circle", {
    id: "level-hover-parcel",
    r: "3.7",
    fill: "#fff",
    stroke: "#d39143",
    "stroke-width": "1.8",
  });
  appendSvgTo(hoverGroup, "circle", {
    id: "level-hover-dewpoint",
    r: "5",
    fill: "#fff",
    stroke: "#267d70",
    "stroke-width": "2.4",
  });
  appendSvgTo(hoverGroup, "rect", {
    id: "level-hover-label-bg",
    width: "176",
    height: "68",
    rx: "3",
    fill: "#fff",
    stroke: "#a99a8d",
    opacity: "0.94",
  });
  appendSvgTo(
    hoverGroup,
    "text",
    {
      id: "level-hover-label",
      fill: "#344b56",
      "font-size": "12",
      "font-weight": "650",
    },
    "",
  );
  ["temperature", "dewpoint", "wind"].forEach((name) => {
    appendSvgTo(
      hoverGroup,
      "text",
      {
        id: `level-hover-${name}-text`,
        fill: "#56666d",
        "font-size": "11",
      },
      "",
    );
  });

  const overlay = appendSvg("rect", {
    x: CHART.humidityLeft - 10,
    y: CHART.top,
    width: CHART.barbsRight - CHART.humidityLeft + 10,
    height: mainHeight,
    fill: "transparent",
    cursor: "crosshair",
    tabindex: "0",
    "aria-label": "Move across pressure levels to inspect sounding data",
    "data-export-exclude": "true",
  });
  const usableLevels = profile.levels.filter(
    (level) =>
      level.pressure_hpa >= pressureTop &&
      level.pressure_hpa <= pressureBottom,
  );
  const inspectAtEvent = (event) => {
    const point = profileChart.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const transformed = point.matrixTransform(
      profileChart.getScreenCTM().inverse(),
    );
    const targetPressure = pressureForY(transformed.y);
    const level = nearestPressureLevel(usableLevels, targetPressure);
    if (level) {
      selectLevel(level, transformed);
    }
  };
  overlay.addEventListener("pointerenter", inspectAtEvent);
  overlay.addEventListener("pointermove", inspectAtEvent);
  overlay.addEventListener("pointerleave", () => {
    profileChart.querySelector("#level-hover")?.setAttribute("visibility", "hidden");
  });
  overlay.addEventListener("pointerdown", (event) => {
    inspectAtEvent(event);
  });

  const initialLevel =
    nearestPressureLevel(usableLevels, 850) ?? usableLevels[0] ?? null;
  if (initialLevel) {
    const diagnosticLevel = diagnostics?.levels
      ? nearestPressureLevel(diagnostics.levels, initialLevel.pressure_hpa)
      : null;
    updateLevelInspector(initialLevel, diagnosticLevel);
  }
}

function drawPressureLevels(yForPressure, pressureTop, pressureBottom) {
  STANDARD_LEVELS.filter(
    (pressure) => pressure >= pressureTop && pressure <= pressureBottom,
  ).forEach((pressure) => {
    const y = yForPressure(pressure);
    const primary = [1000, 850, 700, 500, 300, 200, 100].includes(pressure);
    appendSvg("line", {
      x1: CHART.plotLeft,
      x2: CHART.plotRight,
      y1: y,
      y2: y,
      stroke: "#9b8775",
      "stroke-width": primary ? "0.9" : "0.6",
      opacity: primary ? "0.34" : "0.22",
    });
    appendSvg(
      "text",
      {
        x: CHART.plotLeft - 12,
        y: y + 3,
        fill: primary ? "#52646b" : "#849093",
        "font-size": primary ? "11.5" : "10.5",
        "font-weight": primary ? "650" : "450",
        "text-anchor": "end",
      },
      `${pressure} hPa`,
    );
  });
}

function drawFixedReferenceLevels(
  levels,
  yForPressure,
  pressureTop,
  pressureBottom,
) {
  const references = [
    { pressure: 500, label: "500 hPa", field: "geopotential_height_m", unit: "m" },
    { pressure: 850, label: "850 hPa", field: "temperature_c", unit: "°C" },
  ];
  references.forEach((reference) => {
    if (
      reference.pressure < pressureTop ||
      reference.pressure > pressureBottom
    ) return;
    const level = nearestPressureLevel(levels, reference.pressure);
    if (!level) return;
    const y = yForPressure(reference.pressure);
    const value = level[reference.field];
    appendSvg("line", {
      x1: CHART.plotLeft,
      x2: CHART.plotRight,
      y1: y,
      y2: y,
      stroke: "#2563a9",
      "stroke-width": "1.15",
      "stroke-dasharray": "8 5",
      opacity: "0.66",
    });
    appendSvg(
      "text",
      {
        x: CHART.plotLeft + 8,
        y: y - 6,
        fill: "#2563a9",
        "font-size": "11",
        "font-weight": "700",
        "text-anchor": "start",
      },
      `${reference.label} · ${formatNumber(value, reference.unit === "m" ? 0 : 1)} ${reference.unit}`,
    );
  });
}

function drawTemperatureGrid(
  mode,
  xForTemperature,
  yForPressure,
  pressureTop,
  pressureBottom,
) {
  for (let temperature = -80; temperature <= 50; temperature += 10) {
    const xBottom = xForTemperature(temperature, pressureBottom);
    const xTop = xForTemperature(temperature, pressureTop);
    appendSvg("line", {
      x1: xBottom,
      x2: xTop,
      y1: yForPressure(pressureBottom),
      y2: yForPressure(pressureTop),
      stroke: temperature === 0 ? "#4e78a0" : "#ad9c8e",
      "stroke-width": temperature === 0 ? "1" : "0.55",
      "stroke-dasharray": temperature === 0 ? "5 4" : "none",
      opacity: temperature === 0 ? "0.58" : "0.25",
    });
    if (xBottom >= CHART.plotLeft && xBottom <= CHART.plotRight) {
      appendSvg(
        "text",
        {
          x: xBottom,
          y: CHART.bottom + 18,
          fill: "#758084",
          "font-size": "10.5",
          "text-anchor": "middle",
        },
        `${temperature}`,
      );
    }
  }

  if (mode === "skewt") {
    [-40, -20, 0, 20, 40].forEach((startTemperature) => {
      const points = [1000, 850, 700, 500, 300, 200, 100]
        .filter((pressure) => pressure >= pressureTop)
        .map((pressure) => {
          const approximateDryAdiabat =
            startTemperature + 32 * Math.log(1000 / pressure);
          return `${xForTemperature(approximateDryAdiabat, pressure)},${yForPressure(pressure)}`;
        });
      appendSvg("polyline", {
        points: points.join(" "),
        fill: "none",
        stroke: "#c88b97",
        "stroke-width": "0.55",
        opacity: "0.18",
      });
    });
  }
}

function drawHumidityBand(levels, yForPressure, pressureTop, pressureBottom) {
  const values = levels.filter(
    (level) =>
      level.relative_humidity_pct !== null &&
      level.pressure_hpa >= pressureTop &&
      level.pressure_hpa <= pressureBottom,
  );
  appendSvg("rect", {
    x: CHART.humidityLeft,
    y: CHART.top,
    width: CHART.humidityRight - CHART.humidityLeft,
    height: CHART.bottom - CHART.top,
    fill: "#f3ece3",
    stroke: "#c8b8a8",
  });
  const blurred = appendSvg("g", {
    filter: "url(#humidity-blur)",
    opacity: "0.88",
  });
  drawBandSegments(
    blurred,
    values,
    "relative_humidity_pct",
    CHART.humidityLeft,
    CHART.humidityRight,
    yForPressure,
    humidityColor,
  );
  drawBandLine(
    values,
    "relative_humidity_pct",
    100,
    CHART.humidityLeft,
    CHART.humidityRight,
    yForPressure,
    "#365e62",
  );
}

function drawWindBand(levels, yForPressure, pressureTop, pressureBottom) {
  const values = levels.filter(
    (level) =>
      level.wind_speed_ms !== null &&
      level.pressure_hpa >= pressureTop &&
      level.pressure_hpa <= pressureBottom,
  );
  appendSvg("rect", {
    x: CHART.windLeft,
    y: CHART.top,
    width: CHART.windRight - CHART.windLeft,
    height: CHART.bottom - CHART.top,
    fill: "#f1e9df",
    stroke: "#c8b8a8",
  });
  const group = appendSvg("g", { opacity: "0.92" });
  drawBandSegments(
    group,
    values,
    "wind_speed_ms",
    CHART.windLeft,
    CHART.windRight,
    yForPressure,
    windColor,
  );
  drawBandLine(
    values,
    "wind_speed_ms",
    50,
    CHART.windLeft,
    CHART.windRight,
    yForPressure,
    "#31495e",
  );
}

function drawWindBarbs(levels, yForPressure, pressureTop, pressureBottom) {
  const candidates = levels
    .filter(
      (level) =>
        level.wind_speed_ms !== null &&
        level.wind_direction_deg !== null &&
        level.pressure_hpa >= pressureTop &&
        level.pressure_hpa <= pressureBottom,
    )
    .sort((left, right) => right.pressure_hpa - left.pressure_hpa);
  const selected = [];
  candidates.forEach((level) => {
    const y = yForPressure(level.pressure_hpa);
    if (
      !selected.length ||
      Math.abs(y - selected[selected.length - 1].y) >= 19
    ) {
      selected.push({ level, y });
    }
  });
  const x = (CHART.barbsLeft + CHART.barbsRight) / 2;
  selected.forEach(({ level, y }) => {
    drawWindBarb(
      x,
      y,
      Number(level.wind_direction_deg),
      Number(level.wind_speed_ms),
    );
  });
}

function drawWindBarb(x, y, directionDegrees, speedMs) {
  const group = appendSvg("g", {
    stroke: "#111111",
    fill: "#111111",
    "stroke-width": "1.25",
    "stroke-linecap": "round",
  });
  const speedKnots = Math.max(0, speedMs * 1.94384);
  if (speedKnots < 2.5) {
    appendSvgTo(group, "circle", {
      cx: x,
      cy: y,
      r: 3.2,
      fill: "none",
    });
    return;
  }
  const radians = (directionDegrees * Math.PI) / 180;
  const ux = Math.sin(radians);
  const uy = -Math.cos(radians);
  const px = -uy;
  const py = ux;
  const length = 28;
  const tipX = x + ux * length;
  const tipY = y + uy * length;
  appendSvgTo(group, "line", {
    x1: x,
    y1: y,
    x2: tipX,
    y2: tipY,
  });

  let remaining = Math.round(speedKnots / 5) * 5;
  let offset = 0;
  while (remaining >= 50) {
    const startX = tipX - ux * offset;
    const startY = tipY - uy * offset;
    const backX = startX - ux * 8;
    const backY = startY - uy * 8;
    appendSvgTo(group, "polygon", {
      points: `${startX},${startY} ${backX},${backY} ${backX + px * 9},${backY + py * 9}`,
    });
    remaining -= 50;
    offset += 10;
  }
  while (remaining >= 10) {
    const startX = tipX - ux * offset;
    const startY = tipY - uy * offset;
    appendSvgTo(group, "line", {
      x1: startX,
      y1: startY,
      x2: startX + px * 9 - ux * 4,
      y2: startY + py * 9 - uy * 4,
    });
    remaining -= 10;
    offset += 6;
  }
  if (remaining >= 5) {
    const startX = tipX - ux * offset;
    const startY = tipY - uy * offset;
    appendSvgTo(group, "line", {
      x1: startX,
      y1: startY,
      x2: startX + px * 5 - ux * 2,
      y2: startY + py * 5 - uy * 2,
    });
  }
}

function windComponents(level) {
  if (
    level.wind_speed_ms === null ||
    level.wind_direction_deg === null
  ) {
    return null;
  }
  const radians = (Number(level.wind_direction_deg) * Math.PI) / 180;
  return {
    u: -Number(level.wind_speed_ms) * Math.sin(radians),
    v: -Number(level.wind_speed_ms) * Math.cos(radians),
  };
}

function drawHodograph(levels, diagnostics) {
  const left = CHART.hodoLeft;
  const right = CHART.hodoRight;
  const top = CHART.hodoTop;
  const bottom = CHART.hodoBottom;
  appendSvg("rect", {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
    fill: "#ffffff",
    stroke: "#baa997",
    "stroke-width": "1",
  });
  appendSvg(
    "text",
    {
      x: left + 12,
      y: top + 19,
      fill: "#263943",
      "font-size": "12",
      "font-weight": "700",
      "letter-spacing": "0.5",
    },
    "风矢端图 / 地面相对",
  );

  const windLevels = levels
    .filter(
      (level) =>
        level.geopotential_height_m !== null &&
        windComponents(level) !== null,
    )
    .sort(
      (a, b) =>
        Number(a.geopotential_height_m) -
        Number(b.geopotential_height_m),
    );
  if (windLevels.length < 2) {
    appendSvg(
      "text",
      {
        x: (left + right) / 2,
        y: (top + bottom) / 2,
        fill: "#788286",
        "font-size": "12",
        "text-anchor": "middle",
      },
      "Wind profile unavailable",
    );
    return;
  }
  const surfaceHeight = Number(windLevels[0].geopotential_height_m);
  const points = windLevels
    .map((level) => ({
      ...windComponents(level),
      heightKm:
        (Number(level.geopotential_height_m) - surfaceHeight) / 1000,
    }))
    .filter((point) => point.heightKm >= 0 && point.heightKm <= 12.5);
  const motionPairs = [
    [
      diagnostics?.bunkers_right_motion_u_ms,
      diagnostics?.bunkers_right_motion_v_ms,
    ],
    [
      diagnostics?.bunkers_left_motion_u_ms,
      diagnostics?.bunkers_left_motion_v_ms,
    ],
    [
      diagnostics?.mean_wind_0_6km_u_ms,
      diagnostics?.mean_wind_0_6km_v_ms,
    ],
  ].filter(([u, v]) => Number.isFinite(u) && Number.isFinite(v));
  // Data-focused view: recentre the hodograph on the wind-data bounding box
  // instead of pinning the plot to the calm-wind origin. The origin (0, 0) is
  // always included so the zero-wind reference stays visible, but the view
  // zooms into the actual wind profile.
  const allU = [
    0,
    ...points.map((point) => point.u),
    ...motionPairs.map(([u]) => u),
  ];
  const allV = [
    0,
    ...points.map((point) => point.v),
    ...motionPairs.map(([, v]) => v),
  ];
  const dataCenterU = (Math.min(...allU) + Math.max(...allU)) / 2;
  const dataCenterV = (Math.min(...allV) + Math.max(...allV)) / 2;
  const halfSpan = Math.max(
    (Math.max(...allU) - Math.min(...allU)) / 2,
    (Math.max(...allV) - Math.min(...allV)) / 2,
    10,
  );
  const radius = Math.min(80, Math.max(5, Math.ceil(halfSpan / 5) * 5));
  const centerX = (left + right) / 2;
  const centerY = (top + bottom) / 2 + 10;
  const scale = Math.min(right - left - 42, bottom - top - 58) / (2 * radius);
  const xForU = (u) => centerX + (u - dataCenterU) * scale;
  const yForV = (v) => centerY - (v - dataCenterV) * scale;
  const originX = xForU(0);
  const originY = yForV(0);
  // Clip the wind canvas so focused rings and spokes never bleed outside.
  const hodoDefs = appendSvg("defs");
  const hodoClip = appendSvgTo(hodoDefs, "clipPath", { id: "hodo-clip" });
  appendSvgTo(hodoClip, "rect", {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
  });
  const hodoGroup = appendSvg("g", { "clip-path": "url(#hodo-clip)" });

  for (let ring = 10; ring <= radius; ring += 10) {
    appendSvgTo(hodoGroup, "circle", {
      cx: originX,
      cy: originY,
      r: ring * scale,
      fill: "none",
      stroke: "#9aa3a5",
      "stroke-width": ring === radius ? "0.8" : "0.55",
      "stroke-dasharray": ring === radius ? "none" : "3 3",
      opacity: "0.55",
    });
    appendSvgTo(
      hodoGroup,
      "text",
      {
        x: originX + 3,
        y: originY - ring * scale + 10,
        fill: "#8a9294",
        "font-size": "8",
      },
      `${ring}`,
    );
  }
  appendSvgTo(hodoGroup, "line", {
    x1: originX - radius * scale,
    x2: originX + radius * scale,
    y1: originY,
    y2: originY,
    stroke: "#667174",
    "stroke-width": "0.8",
  });
  const lowLevelPoints = points.filter((point) => point.heightKm <= 3.1);
  if (lowLevelPoints.length >= 2) {
    const turning = lowLevelPoints.slice(1).reduce(
      (sum, point, index) => {
        const previous = lowLevelPoints[index];
        return sum + previous.u * point.v - previous.v * point.u;
      },
      0,
    );
    appendSvgTo(hodoGroup, "polygon", {
      points: [
        `${xForU(0)},${yForV(0)}`,
        ...lowLevelPoints.map((point) => `${xForU(point.u)},${yForV(point.v)}`),
      ].join(" "),
      fill: turning < 0 ? "#f2c94c" : "#126e68",
      opacity: "0.2",
      stroke: turning < 0 ? "#d5aa18" : "#126e68",
      "stroke-width": "1.1",
      "stroke-linejoin": "round",
    });
    // Low-level spokes make the clockwise/counter-clockwise turning sector
    // legible without obscuring the observed hodograph.
    lowLevelPoints.forEach((point, index) => {
      if (index % Math.max(1, Math.ceil(lowLevelPoints.length / 12)) !== 0) {
        return;
      }
      appendSvgTo(hodoGroup, "line", {
        x1: xForU(0),
        y1: yForV(0),
        x2: xForU(point.u),
        y2: yForV(point.v),
        stroke: turning < 0 ? "#d5aa18" : "#126e68",
        "stroke-width": "0.7",
        opacity: "0.32",
      });
    });
  }
  appendSvgTo(hodoGroup, "line", {
    x1: xForU(0),
    y1: yForV(0),
    x2: xForU(points[0].u),
    y2: yForV(points[0].v),
    stroke: "#263943",
    "stroke-width": "1.4",
    "stroke-dasharray": "3 3",
    opacity: "0.72",
  });
  appendSvgTo(hodoGroup, "line", {
    x1: originX,
    x2: originX,
    y1: originY - radius * scale,
    y2: originY + radius * scale,
    stroke: "#667174",
    "stroke-width": "0.8",
  });
  const heightColor = (heightKm) => {
    if (heightKm <= 1) return "#d94b45";
    if (heightKm <= 3) return "#e27b22";
    if (heightKm <= 6) return "#c49a00";
    if (heightKm <= 9) return "#3568c8";
    return "#7b8588";
  };
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    appendSvgTo(hodoGroup, "line", {
      x1: xForU(start.u),
      y1: yForV(start.v),
      x2: xForU(end.u),
      y2: yForV(end.v),
      stroke: heightColor((start.heightKm + end.heightKm) / 2),
      "stroke-width": "3",
      "stroke-linecap": "round",
    });
  }
  [1, 3, 6, 9, 12].forEach((heightKm) => {
    const point = points.reduce((nearest, candidate) =>
      Math.abs(candidate.heightKm - heightKm) <
      Math.abs(nearest.heightKm - heightKm)
        ? candidate
        : nearest,
    );
    if (Math.abs(point.heightKm - heightKm) > 1) {
      return;
    }
    appendSvgTo(hodoGroup, "line", {
      x1: xForU(0),
      y1: yForV(0),
      x2: xForU(point.u),
      y2: yForV(point.v),
      stroke: heightColor(point.heightKm),
      "stroke-width": "0.7",
      opacity: "0.22",
    });
    appendSvgTo(hodoGroup, "circle", {
      cx: xForU(point.u),
      cy: yForV(point.v),
      r: 2.8,
      fill: "#111",
    });
    appendSvgTo(
      hodoGroup,
      "text",
      {
        x: xForU(point.u) + 5,
        y: yForV(point.v) - 5,
        fill: "#263943",
        "font-size": "10",
        "font-weight": "700",
      },
      `${heightKm}`,
    );
  });
  drawHodographMotion(
    "RM",
    diagnostics?.bunkers_right_motion_u_ms,
    diagnostics?.bunkers_right_motion_v_ms,
    "#cc4fa2",
    xForU,
    yForV,
    hodoGroup,
  );
  drawHodographMotion(
    "LM",
    diagnostics?.bunkers_left_motion_u_ms,
    diagnostics?.bunkers_left_motion_v_ms,
    "#476ee8",
    xForU,
    yForV,
    hodoGroup,
  );
  drawHodographMotion(
    "MW",
    diagnostics?.mean_wind_0_6km_u_ms,
    diagnostics?.mean_wind_0_6km_v_ms,
    "#6d7679",
    xForU,
    yForV,
    hodoGroup,
  );
  appendSvg(
    "text",
    {
      x: right - 10,
      y: bottom - 9,
      fill: "#788286",
      "font-size": "9.5",
      "text-anchor": "end",
    },
    "m/s · height labels in km AGL",
  );
}

function drawThetaE(diagnosticLevels, yForPressure) {
  const left = CHART.thetaeLeft;
  const right = CHART.thetaeRight;
  const top = CHART.thetaeTop;
  const bottom = CHART.thetaeBottom;
  // The small frame shares the exact top/bottom edges with the hodograph so
  // the two panels line up; the header reserves a fixed strip at the top.
  const headerHeight = 34;
  const thetaEMinK = 320;
  const thetaEMaxK = 400;
  const xForThetaE = (thetaE) =>
    left + ((thetaE - thetaEMinK) / (thetaEMaxK - thetaEMinK)) * (right - left);
  const yForThetaE = (pressure) => {
    const fraction = (yForPressure(pressure) - top) / (bottom - top);
    return top + headerHeight + fraction * (bottom - top - headerHeight);
  };
  appendSvg("rect", {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
    fill: "#ffffff",
    stroke: "#baa997",
    "stroke-width": "1",
  });
  appendSvg(
    "text",
    {
      x: left + 10,
      y: top + 19,
      fill: "#263943",
      "font-size": "12",
      "font-weight": "700",
      "letter-spacing": "0.5",
    },
    "θe (K)",
  );
  [320, 340, 360, 380, 400].forEach((thetaE) => {
    appendSvg(
      "text",
      {
        x: xForThetaE(thetaE),
        y: top + 30,
        fill: "#8a5a2b",
        "font-size": "9",
        "text-anchor": "middle",
      },
      `${thetaE}`,
    );
  });
  if (!diagnosticLevels?.length) {
    appendSvg(
      "text",
      {
        x: (left + right) / 2,
        y: (top + bottom) / 2,
        fill: "#788286",
        "font-size": "11",
        "text-anchor": "middle",
      },
      "No profile",
    );
    return;
  }
  const thetaeDefs = appendSvg("defs");
  const thetaeClip = appendSvgTo(thetaeDefs, "clipPath", {
    id: "thetae-clip",
  });
  appendSvgTo(thetaeClip, "rect", {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
  });
  const thetaeGroup = appendSvg("g", { "clip-path": "url(#thetae-clip)" });
  appendSvgTo(thetaeGroup, "path", {
    d: diagnosticPath(
      diagnosticLevels,
      "equivalent_potential_temperature_k",
      (thetaE) => xForThetaE(thetaE),
      yForThetaE,
    ),
    fill: "none",
    stroke: "#8a5a2b",
    "stroke-width": "2",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  });
  appendSvg(
    "text",
    {
      x: right - 8,
      y: bottom - 9,
      fill: "#788286",
      "font-size": "9",
      "text-anchor": "end",
    },
    "320–400 K",
  );
}

function drawHodographMotion(label, u, v, color, xForU, yForV, group) {
  if (!Number.isFinite(u) || !Number.isFinite(v)) {
    return;
  }
  const x = xForU(u);
  const y = yForV(v);
  const target = group || profileChart;
  appendSvgTo(target, "rect", {
    x: x - 3.5,
    y: y - 3.5,
    width: 7,
    height: 7,
    fill: "#fff",
    stroke: color,
    "stroke-width": "2",
  });
  appendSvgTo(
    target,
    "text",
    {
      x: x + 6,
      y: y - 6,
      fill: color,
      "font-size": "10",
      "font-weight": "700",
    },
    label,
  );
}

function drawBandSegments(
  group,
  levels,
  attribute,
  left,
  right,
  yForPressure,
  colorFunction,
) {
  levels.forEach((level, index) => {
    const previous = levels[index - 1];
    const next = levels[index + 1];
    const y = yForPressure(level.pressure_hpa);
    const boundaryBelow = previous
      ? (yForPressure(previous.pressure_hpa) + y) / 2
      : CHART.bottom;
    const boundaryAbove = next
      ? (yForPressure(next.pressure_hpa) + y) / 2
      : CHART.top;
    appendSvgTo(group, "rect", {
      x: left,
      y: Math.min(boundaryAbove, boundaryBelow),
      width: right - left,
      height: Math.max(1, Math.abs(boundaryBelow - boundaryAbove) + 1),
      fill: colorFunction(level[attribute]),
    });
  });
}

function drawBandLine(
  levels,
  attribute,
  maximum,
  left,
  right,
  yForPressure,
  color,
) {
  const points = levels
    .map((level) => {
      const fraction = clamp(level[attribute] / maximum, 0, 1);
      return `${left + fraction * (right - left)},${yForPressure(level.pressure_hpa)}`;
    })
    .join(" ");
  appendSvg("polyline", {
    points,
    fill: "none",
    stroke: "#ffffff",
    "stroke-width": "3.4",
    opacity: "0.45",
  });
  appendSvg("polyline", {
    points,
    fill: "none",
    stroke: color,
    "stroke-width": "1",
    opacity: "0.8",
  });
}

function joinDiagnosticLevels(profileLevels, diagnostics) {
  if (!diagnostics?.levels?.length) {
    return [];
  }
  const environmentByPressure = new Map(
    profileLevels
      .filter((level) => level.temperature_c !== null)
      .map((level) => [
        Number(level.pressure_hpa).toFixed(3),
        level.temperature_c,
      ]),
  );
  return diagnostics.levels
    .map((level) => ({
      ...level,
      environment_temperature_c: environmentByPressure.get(
        Number(level.pressure_hpa).toFixed(3),
      ),
    }))
    .filter((level) => level.environment_temperature_c !== undefined);
}

function drawEnergyAreas(
  levels,
  diagnostics,
  xForTemperature,
  yForPressure,
) {
  for (let index = 0; index < levels.length - 1; index += 1) {
    const lower = levels[index];
    const upper = levels[index + 1];
    const middlePressure = Math.sqrt(
      lower.pressure_hpa * upper.pressure_hpa,
    );
    const difference =
      ((lower.parcel_temperature_c - lower.environment_temperature_c) +
        (upper.parcel_temperature_c - upper.environment_temperature_c)) /
      2;
    const insideCapeLayer =
      diagnostics.lfc_pressure_hpa !== null &&
      middlePressure <= diagnostics.lfc_pressure_hpa &&
      (diagnostics.equilibrium_level_pressure_hpa === null ||
        middlePressure >= diagnostics.equilibrium_level_pressure_hpa);
    const isCape = insideCapeLayer && difference > 0;
    const isCin =
      difference < 0 &&
      (diagnostics.lfc_pressure_hpa === null ||
        middlePressure >= diagnostics.lfc_pressure_hpa);
    if (!isCape && !isCin) {
      continue;
    }
    const points = [
      [
        xForTemperature(
          lower.environment_temperature_c,
          lower.pressure_hpa,
        ),
        yForPressure(lower.pressure_hpa),
      ],
      [
        xForTemperature(
          upper.environment_temperature_c,
          upper.pressure_hpa,
        ),
        yForPressure(upper.pressure_hpa),
      ],
      [
        xForTemperature(upper.parcel_temperature_c, upper.pressure_hpa),
        yForPressure(upper.pressure_hpa),
      ],
      [
        xForTemperature(lower.parcel_temperature_c, lower.pressure_hpa),
        yForPressure(lower.pressure_hpa),
      ],
    ];
    appendSvg("polygon", {
      points: points.map((point) => point.join(",")).join(" "),
      fill: isCape ? "#eaa66c" : "#77a7c9",
      opacity: isCape ? "0.27" : "0.24",
      "clip-path": "url(#plot-clip)",
    });
  }
}

function drawDiagnosticLevel(
  label,
  pressure,
  color,
  yForPressure,
  pressureTop,
  pressureBottom,
  labelIndex,
) {
  if (
    pressure === null ||
    pressure === undefined ||
    pressure < pressureTop ||
    pressure > pressureBottom
  ) {
    return;
  }
  const y = yForPressure(pressure);
  appendSvg("line", {
    x1: CHART.plotLeft,
    x2: CHART.plotRight,
    y1: y,
    y2: y,
    stroke: color,
    "stroke-width": "1",
    "stroke-dasharray": label === "0 °C" ? "3 4" : "7 4",
    opacity: "0.68",
  });
  appendSvg(
    "text",
    {
      x: CHART.plotRight - 7,
      y: y - 5 - (labelIndex % 2) * 9,
      fill: color,
      "font-size": "10.5",
      "font-weight": "650",
      "text-anchor": "end",
    },
    `${label} ${formatNumber(pressure, 0)} hPa`,
  );
}

function diagnosticPath(
  levels,
  attribute,
  xForTemperature,
  yForPressure,
) {
  return levels
    .map((level, index) => {
      const prefix = index === 0 ? "M" : "L";
      return `${prefix}${xForTemperature(level[attribute], level.pressure_hpa).toFixed(1)},${yForPressure(level.pressure_hpa).toFixed(1)}`;
    })
    .join(" ");
}

function drawChartLegend() {
  const entries = [
    ["T", "#df2727", ""],
    ["Td", "#267d70", ""],
    ["Tw", "#3d9fc4", ""],
    ["Tv", "#8463a6", "7 4"],
    ["气块", "#d39143", "3 4"],
    ["正浮力", "#eaa66c", ""],
    ["负浮力", "#77a7c9", ""],
  ];
  let x = 250;
  entries.forEach(([label, color, dash]) => {
    appendSvg("line", {
      x1: x,
      x2: x + 14,
      y1: 67,
      y2: 67,
      stroke: color,
      "stroke-width": label === "正浮力" || label === "负浮力" ? "6" : "2",
      "stroke-dasharray": dash,
      opacity: label === "正浮力" || label === "负浮力" ? "0.55" : "1",
    });
    appendSvg(
      "text",
      {
        x: x + 19,
        y: 70,
        fill: "#657175",
        "font-size": "13",
      },
      label,
    );
    x += label === "气块" ? 86 : 66;
  });
}

function drawDiagnosticColumn(diagnostics) {
  const left = CHART.hodoLeft;
  const right = CHART.thetaeRight;
  const top = CHART.diagnosticsTop;
  const bottom = CHART.diagnosticsBottom;
  appendSvg("rect", {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
    fill: "#ffffff",
    stroke: "#baa997",
    "stroke-width": "1",
  });
  appendSvg(
    "text",
    {
      x: left + 12,
      y: top + 19,
      fill: "#263943",
      "font-size": "12",
      "font-weight": "700",
      "letter-spacing": "0.6",
    },
    "对流诊断",
  );
  appendSvg("line", {
    x1: left,
    x2: right,
    y1: top + 29,
    y2: top + 29,
    stroke: "#ded5cc",
    "stroke-width": "1",
  });

  if (!diagnostics) {
    appendSvg(
      "text",
      {
        x: (left + right) / 2,
        y: top + 60,
        fill: "#788286",
        "font-size": "11",
        "text-anchor": "middle",
      },
      "暂无诊断",
    );
    drawConvectiveToneLegend();
    return;
  }
  const gap = 10;
  const legendHeight = 56;
  const groupsBottom = bottom - legendHeight;
  const groupWidth = (right - left - gap * 3) / 2;
  const groupHeight = (groupsBottom - top - 51 - gap) / 2;
  const firstX = left + gap;
  const secondX = firstX + groupWidth + gap;
  const firstY = top + 44;
  const secondY = firstY + groupHeight + gap;
  drawDiagnosticGroup(
    "气块能量",
    [
      ["cape", "地面气块正能", diagnostics.cape_j_kg, `${formatNumber(diagnostics.cape_j_kg, 0)} J/kg`],
      ["cin", "地面气块抑制", diagnostics.cin_j_kg, `${formatNumber(diagnostics.cin_j_kg, 0)} J/kg`],
      ["cape", "混合层正能", diagnostics.mixed_layer_cape_j_kg, `${formatNumber(diagnostics.mixed_layer_cape_j_kg, 0)} J/kg`],
      ["cin", "混合层抑制", diagnostics.mixed_layer_cin_j_kg, `${formatNumber(diagnostics.mixed_layer_cin_j_kg, 0)} J/kg`],
      ["cape", "最不稳定正能", diagnostics.most_unstable_cape_j_kg, `${formatNumber(diagnostics.most_unstable_cape_j_kg, 0)} J/kg`],
      ["cin", "最不稳定抑制", diagnostics.most_unstable_cin_j_kg, `${formatNumber(diagnostics.most_unstable_cin_j_kg, 0)} J/kg`],
      ["dcape", "下沉对流能", diagnostics.dcape_j_kg, `${formatNumber(diagnostics.dcape_j_kg, 0)} J/kg`],
    ],
    firstX,
    firstY,
    groupWidth,
    groupHeight,
  );
  drawDiagnosticGroup(
    "高度与水汽",
    [
      ["lclHeight", "抬升凝结高度", diagnostics.lcl_height_agl_m, `${formatNumber(diagnostics.lcl_height_agl_m, 0)} m`],
      ["lfcHeight", "自由对流高度", diagnostics.lfc_height_agl_m, `${formatNumber(diagnostics.lfc_height_agl_m, 0)} m`],
      ["elHeight", "平衡高度", diagnostics.equilibrium_level_height_agl_m, `${formatNumber(diagnostics.equilibrium_level_height_agl_m, 0)} m`],
      ["freezing", "零度层海拔", diagnostics.freezing_level_height_m, `${formatNumber(diagnostics.freezing_level_height_m, 0)} m`],
      ["pwat", "整层可降水量", diagnostics.precipitable_water_mm, `${formatNumber(diagnostics.precipitable_water_mm, 1)} mm`],
      ["lapse", "700—500递减率", diagnostics.lapse_rate_700_500_c_km, `${formatNumber(diagnostics.lapse_rate_700_500_c_km, 1)} °C/km`],
    ],
    secondX,
    firstY,
    groupWidth,
    groupHeight,
  );
  drawDiagnosticGroup(
    "风场与风矢端图",
    [
      ["shear", "SHR 0–1 km", diagnostics.bulk_shear_0_1km_ms, `${formatNumber(diagnostics.bulk_shear_0_1km_ms, 1)} m/s`],
      ["shear", "SHR 0–3 km", diagnostics.bulk_shear_0_3km_ms, `${formatNumber(diagnostics.bulk_shear_0_3km_ms, 1)} m/s`],
      ["shear", "SHR 0–6 km", diagnostics.bulk_shear_0_6km_ms, `${formatNumber(diagnostics.bulk_shear_0_6km_ms, 1)} m/s`],
      ["srh", "SRH 0–1 km", diagnostics.storm_relative_helicity_0_1km_m2_s2, `${formatNumber(diagnostics.storm_relative_helicity_0_1km_m2_s2, 0)} m²/s²`],
      ["srh", "SRH 0–3 km", diagnostics.storm_relative_helicity_0_3km_m2_s2, `${formatNumber(diagnostics.storm_relative_helicity_0_3km_m2_s2, 0)} m²/s²`],
      ["neutral", "右移风暴运动", diagnostics.bunkers_right_motion_u_ms, vectorMotionText(diagnostics.bunkers_right_motion_u_ms, diagnostics.bunkers_right_motion_v_ms)],
      ["neutral", "0—6千米平均风", diagnostics.mean_wind_0_6km_u_ms, vectorMotionText(diagnostics.mean_wind_0_6km_u_ms, diagnostics.mean_wind_0_6km_v_ms)],
      ["angle", "临界角", diagnostics.critical_angle_deg, `${formatNumber(diagnostics.critical_angle_deg, 0)}°`],
    ],
    firstX,
    secondY,
    groupWidth,
    groupHeight,
  );
  drawDiagnosticGroup(
    "综合与传统指数",
    [
      ["li", "抬升指数", diagnostics.lifted_index_c, `${formatNumber(diagnostics.lifted_index_c, 1)} °C`],
      ["k", "K指数", diagnostics.k_index_c, formatNumber(diagnostics.k_index_c, 1)],
      ["tt", "总指数", diagnostics.total_totals_index, formatNumber(diagnostics.total_totals_index, 1)],
      ["sweat", "强天气威胁指数", diagnostics.sweat_index, formatNumber(diagnostics.sweat_index, 0)],
      ["stp", "固定层显著龙卷参数", diagnostics.significant_tornado_fixed, formatNumber(diagnostics.significant_tornado_fixed, 2)],
    ],
    secondX,
    secondY,
    groupWidth,
    groupHeight,
  );
  drawConvectiveToneLegend();
}

function drawDiagnosticGroup(title, entries, x, y, width, height) {
  appendSvg("rect", {
    x,
    y,
    width,
    height,
    fill: "#ffffff",
    stroke: "#eee8e2",
    "stroke-width": "1",
  });
  appendSvg(
    "text",
    {
      x: x + 8,
      y: y + 14,
      fill: "#697579",
      "font-size": "11.5",
      "font-weight": "700",
      "letter-spacing": "0.45",
    },
    title,
  );
  const rowHeight = (height - 30) / entries.length;
  entries.forEach(([key, label, rawValue, displayValue], index) => {
    const rowY = y + 31 + index * rowHeight;
    appendSvg(
      "text",
      {
        x: x + 8,
        y: rowY,
        fill: "#788286",
        "font-size": "11.5",
      },
      label,
    );
    appendSvg(
      "text",
      {
        x: x + width - 8,
        y: rowY,
        fill: convectiveToneColor(key, rawValue),
        "font-size": "11.5",
        "font-weight": "700",
        "text-anchor": "end",
      },
      displayValue,
    );
  });
}

function vectorMotionText(u, v) {
  if (!Number.isFinite(u) || !Number.isFinite(v)) {
    return "—";
  }
  const speed = Math.hypot(u, v);
  const direction = (
    (Math.atan2(u, v) * 180) / Math.PI +
    360
  ) % 360;
  return `${formatNumber(direction, 0)}° / ${formatNumber(speed, 1)} m/s`;
}

function convectiveTone(key, value) {
  if (!Number.isFinite(value)) {
    return "weak";
  }
  const thresholds = {
    cape: [100, 1000, 2500, 4000],
    cin: [-200, -50, -10, 0],
    pwat: [20, 40, 55, 70],
    k: [20, 30, 35, 40],
    tt: [44, 48, 52, 56],
    shear: [8, 15, 25, 32],
    lapse: [5.5, 6.5, 7.5, 8.5],
    dcape: [500, 1000, 1500, 2000],
    elHeight: [7000, 10000, 13000, 16000],
    srh: [50, 100, 200, 300],
    angle: [45, 75, 110, 140],
    sweat: [200, 300, 400, 500],
    stp: [0.5, 1, 3, 5],
  };
  const reverseThresholds = {
    li: [2, 0, -3, -6],
    lclHeight: [2000, 1500, 750, 400],
    lfcHeight: [3000, 2000, 1000, 500],
  };
  const tones = ["weak", "possible", "favourable", "veryFavourable", "extreme"];
  if (thresholds[key]) {
    const index = thresholds[key].findIndex((threshold) => value < threshold);
    return tones[index === -1 ? 4 : index];
  }
  if (reverseThresholds[key]) {
    const index = reverseThresholds[key].findIndex((threshold) => value > threshold);
    return tones[index === -1 ? 4 : index];
  }
  // Directional vectors and reference levels are not independently
  // interpretable as convective probability.
  return "weak";
}

function convectiveToneColor(key, value) {
  const tone = convectiveTone(key, value);
  return {
    weak: "#557a9b",
    possible: "#d5aa18",
    favourable: "#e47722",
    veryFavourable: "#c83b4d",
    extreme: "#a02c86",
  }[tone];
}

function drawConvectiveToneLegend() {
  const entries = [
    ["弱", "#557a9b"],
    ["可能", "#d5aa18"],
    ["有利", "#e47722"],
    ["很有利", "#c83b4d"],
    ["极端", "#822c83"],
  ];
  const left = CHART.hodoLeft;
  const right = CHART.thetaeRight;
  const bottom = CHART.diagnosticsBottom;
  const legendLeft = left + 10;
  const legendRight = right - 10;
  const segmentWidth = (legendRight - legendLeft) / entries.length;
  appendSvg("line", {
    x1: left,
    x2: right,
    y1: bottom - 48,
    y2: bottom - 48,
    stroke: "#ded5cc",
    "stroke-width": "1",
  });
  appendSvg(
    "text",
    {
      x: legendLeft,
      y: bottom - 37,
      fill: "#59686d",
      "font-size": "11.5",
      "font-weight": "700",
      "letter-spacing": "0.35",
    },
    "对流有利程度",
  );
  entries.forEach(([label, color], index) => {
    const x = legendLeft + index * segmentWidth;
    appendSvg("rect", {
      x,
      y: bottom - 30,
      width: segmentWidth,
      height: 28,
      fill: color,
      stroke: "#ffffff",
      "stroke-width": "1",
    });
    appendSvg(
      "text",
      {
        x: x + segmentWidth / 2,
        y: bottom - 12,
        fill: index === 1 ? "#263943" : "#ffffff",
        "font-size": "8.8",
        "font-weight": "700",
        "text-anchor": "middle",
      },
      label,
    );
  });
}

function profilePath(
  levels,
  attribute,
  xForTemperature,
  yForPressure,
  pressureTop,
  pressureBottom,
) {
  let drawing = false;
  return levels
    .map((level) => {
      const value = level[attribute];
      const usable =
        value !== null &&
        level.pressure_hpa >= pressureTop &&
        level.pressure_hpa <= pressureBottom;
      if (!usable) {
        drawing = false;
        return "";
      }
      const prefix = drawing ? "L" : "M";
      drawing = true;
      return `${prefix}${xForTemperature(value, level.pressure_hpa).toFixed(1)},${yForPressure(level.pressure_hpa).toFixed(1)}`;
    })
    .filter(Boolean)
    .join(" ");
}

function selectLevel(level, cursorPoint = null) {
  if (!level || !chartProjection) {
    return;
  }
  const y = chartProjection.yForPressure(level.pressure_hpa);
  const group = profileChart.querySelector("#level-hover");
  const line = profileChart.querySelector("#level-hover-line");
  const verticalLine = profileChart.querySelector("#level-hover-vertical");
  const temperatureMarker = profileChart.querySelector(
    "#level-hover-temperature",
  );
  const dewpointMarker = profileChart.querySelector("#level-hover-dewpoint");
  const virtualMarker = profileChart.querySelector("#level-hover-virtual");
  const parcelMarker = profileChart.querySelector("#level-hover-parcel");
  const labelBackground = profileChart.querySelector("#level-hover-label-bg");
  const label = profileChart.querySelector("#level-hover-label");
  const temperatureText = profileChart.querySelector(
    "#level-hover-temperature-text",
  );
  const dewpointText = profileChart.querySelector(
    "#level-hover-dewpoint-text",
  );
  const windText = profileChart.querySelector("#level-hover-wind-text");
  group.setAttribute("visibility", "visible");
  line.setAttribute("y1", y);
  line.setAttribute("y2", y);

  positionProfileMarker(
    temperatureMarker,
    level.temperature_c,
    level.pressure_hpa,
    y,
  );
  positionProfileMarker(
    dewpointMarker,
    level.dewpoint_c,
    level.pressure_hpa,
    y,
  );
  const diagnostics = activeDiagnostics();
  const diagnosticLevel = diagnostics?.levels
    ? nearestPressureLevel(
        diagnostics.levels,
        level.pressure_hpa,
      )
    : null;
  positionProfileMarker(
    virtualMarker,
    diagnosticLevel?.virtual_temperature_c ?? null,
    level.pressure_hpa,
    y,
  );
  positionProfileMarker(
    parcelMarker,
    diagnosticLevel?.parcel_temperature_c ?? null,
    level.pressure_hpa,
    y,
  );

  const cursorX = clamp(
    cursorPoint?.x ?? CHART.plotRight - 184,
    CHART.plotLeft,
    CHART.plotRight,
  );
  verticalLine.setAttribute("x1", cursorX);
  verticalLine.setAttribute("x2", cursorX);
  const labelX = cursorX > CHART.plotRight - 190
    ? cursorX - 184
    : cursorX + 8;
  const labelY = clamp(
    (cursorPoint?.y ?? y) - 76,
    CHART.top + 5,
    CHART.bottom - 73,
  );
  labelBackground.setAttribute("x", labelX);
  labelBackground.setAttribute("y", labelY);
  label.setAttribute("x", labelX + 8);
  label.setAttribute("y", labelY + 15);
  label.textContent =
    `${formatNumber(level.pressure_hpa, 1)} hPa  |  H ${formatNumber(level.geopotential_height_m, 0)} m`;
  temperatureText.setAttribute("x", labelX + 8);
  temperatureText.setAttribute("y", labelY + 29);
  temperatureText.textContent =
    `T ${formatNumber(level.temperature_c, 1)}°  |  Tw ${formatNumber(diagnosticLevel?.wet_bulb_temperature_c, 1)}°  |  Tv ${formatNumber(diagnosticLevel?.virtual_temperature_c, 1)}°`;
  dewpointText.setAttribute("x", labelX + 8);
  dewpointText.setAttribute("y", labelY + 43);
  dewpointText.textContent =
    `Td ${formatNumber(level.dewpoint_c, 1)} °C  |  RH ${formatNumber(level.relative_humidity_pct, 0)}%`;
  windText.setAttribute("x", labelX + 8);
  windText.setAttribute("y", labelY + 57);
  windText.textContent = level.wind_speed_ms === null
    ? "Wind —"
    : `${windDirectionName(level.wind_direction_deg)}  ${formatNumber(level.wind_speed_ms, 1)} m/s`;
  updateLevelInspector(level, diagnosticLevel);
}

function positionProfileMarker(marker, value, pressure, y) {
  if (value === null) {
    marker.setAttribute("visibility", "hidden");
    return;
  }
  marker.setAttribute("visibility", "visible");
  marker.setAttribute("cx", chartProjection.xForTemperature(value, pressure));
  marker.setAttribute("cy", y);
}

function updateLevelInspector(level, diagnosticLevel) {
  levelPressure.textContent = `${formatNumber(level.pressure_hpa, 1)} hPa`;
  levelHeight.textContent =
    level.geopotential_height_m === null
      ? "Geopotential height —"
      : `Geopotential height ${formatNumber(level.geopotential_height_m, 0)} m`;
  const values = [
    formatUnit(level.temperature_c, "°C", 1),
    formatUnit(level.dewpoint_c, "°C", 1),
    formatUnit(diagnosticLevel?.wet_bulb_temperature_c, "°C", 1),
    formatUnit(diagnosticLevel?.virtual_temperature_c, "°C", 1),
    formatUnit(diagnosticLevel?.parcel_temperature_c, "°C", 1),
    formatUnit(level.relative_humidity_pct, "%", 0),
    level.wind_speed_ms === null
      ? "—"
      : `${windDirectionName(level.wind_direction_deg)} · ${formatNumber(level.wind_direction_deg, 0)}° / ${formatNumber(level.wind_speed_ms, 1)} m/s`,
  ];
  levelValues.querySelectorAll("dd").forEach((element, index) => {
    element.textContent = values[index];
  });
}

function windDirectionName(direction) {
  if (direction === null || direction === undefined) {
    return "风向不详";
  }
  const names = [
    "北风",
    "北偏东北风",
    "东北风",
    "东北偏东风",
    "东风",
    "东南偏东风",
    "东南风",
    "南偏东南风",
    "南风",
    "南偏西南风",
    "西南风",
    "西南偏西风",
    "西风",
    "西北偏西风",
    "西北风",
    "西北偏北风",
  ];
  const normalized = ((Number(direction) % 360) + 360) % 360;
  return names[Math.round(normalized / 22.5) % 16];
}

function renderSourceTable(levels) {
  sourceTableBody.innerHTML = levels
    .map(
      (level) => `
        <tr>
          <td>${formatUnit(level.pressure_hpa, " hPa", 1)}</td>
          <td>${formatUnit(level.geopotential_height_m, " m", 0)}</td>
          <td>${formatUnit(level.temperature_c, " °C", 1)}</td>
          <td>${formatUnit(level.dewpoint_c, " °C", 1)}</td>
          <td>${formatUnit(level.relative_humidity_pct, " %", 0)}</td>
          <td>${formatUnit(level.wind_direction_deg, "°", 0)}</td>
          <td>${formatUnit(level.wind_speed_ms, " m/s", 1)}</td>
        </tr>
      `,
    )
    .join("");
}

function populateCorrectionFields(profile) {
  const surface = [...profile.levels]
    .filter((level) => level.temperature_c !== null && level.dewpoint_c !== null)
    .sort((left, right) => right.pressure_hpa - left.pressure_hpa)[0];
  if (!surface) {
    return;
  }
  correctionPressure.value = surface.pressure_hpa.toFixed(1);
  correctionTemperature.value = surface.temperature_c.toFixed(1);
  correctionDewpoint.value = surface.dewpoint_c.toFixed(1);
  correctionTime.value = chinaLocalHour(profile.valid_at);
  correctionStatus.textContent =
    "订正只作用于当前交互图与本次导出，不改写归档资料。";
}

function chinaLocalHour(isoTime) {
  const date = new Date(new Date(isoTime).getTime() + 8 * 60 * 60 * 1000);
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  const hour = String(date.getUTCHours()).padStart(2, "0");
  return `${year}-${month}-${day}T${hour}:00`;
}

function dewpointFromTemperatureHumidity(temperature, relativeHumidity) {
  const humidity = clamp(relativeHumidity, 1, 100) / 100;
  const a = 17.625;
  const b = 243.04;
  const gamma = Math.log(humidity) + (a * temperature) / (b + temperature);
  return (b * gamma) / (a - gamma);
}

async function applySoundingCorrection(sourceLabel = "manual") {
  if (!currentSounding) {
    return;
  }
  const payload = {
    pressure_hpa: Number(correctionPressure.value),
    temperature_c: Number(correctionTemperature.value),
    dewpoint_c: Number(correctionDewpoint.value),
    source_label: sourceLabel,
  };
  correctionStatus.textContent = "正在重新计算气块廓线和热力诊断……";
  const response = await fetch(
    `/api/v1/soundings/${currentSounding.stationId}/correct?${currentSounding.query}`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail ?? `HTTP ${response.status}`);
  }
  currentSounding.corrected = data;
  correctionStatus.textContent =
    `已应用 ${sourceLabel} 地面订正；CAPE、CIN、LCL、LFC、EL 与各指数均已重算。`;
  renderSoundingSummary();
  renderSelectedView();
}

async function loadHourlyCorrection() {
  if (!currentSounding) {
    return;
  }
  if (!correctionTime.value || !correctionTime.value.endsWith(":00")) {
    throw new Error("请选择一个整点时刻");
  }
  correctionStatus.textContent = "正在读取所选整点的气压、温度和湿度……";
  const query = new URLSearchParams({
    time: `${correctionTime.value}:00+08:00`,
  });
  const response = await fetch(
    `/api/v1/observations/hourly/${currentSounding.stationId}?${query.toString()}`,
    { headers: { Accept: "application/json" } },
  );
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail ?? `HTTP ${response.status}`);
  }
  if (
    !Number.isFinite(data.station_pressure_hpa)
    || !Number.isFinite(data.temperature_c)
    || !Number.isFinite(data.relative_humidity_pct)
  ) {
    throw new Error("整点资料缺少气压、温度或相对湿度，无法自动订正");
  }
  correctionPressure.value = Number(data.station_pressure_hpa).toFixed(1);
  correctionTemperature.value = Number(data.temperature_c).toFixed(1);
  correctionDewpoint.value = dewpointFromTemperatureHumidity(
    Number(data.temperature_c),
    Number(data.relative_humidity_pct),
  ).toFixed(1);
  await applySoundingCorrection(
    `q-weather hourly ${correctionTime.value.replace("T", " ")} CST`,
  );
}

function nearestPressureLevel(levels, pressure) {
  return levels.reduce((closest, level) => {
    if (!closest) {
      return level;
    }
    return Math.abs(Math.log(level.pressure_hpa / pressure)) <
      Math.abs(Math.log(closest.pressure_hpa / pressure))
      ? level
      : closest;
  }, null);
}

function appendSvg(tag, attributes = {}, text = null) {
  return appendSvgTo(profileChart, tag, attributes, text);
}

function appendSvgTo(parent, tag, attributes = {}, text = null) {
  const element = document.createElementNS(SVG_NS, tag);
  Object.entries(attributes).forEach(([name, value]) => {
    element.setAttribute(name, String(value));
  });
  if (text !== null) {
    element.textContent = text;
  }
  parent.append(element);
  return element;
}

function humidityColor(value) {
  const fraction = clamp((value - 15) / 85, 0, 1);
  return interpolateColor(["#ffffff", "#d7efeb", "#75c9bd", "#126e68"], fraction);
}

function windColor(value) {
  const fraction = clamp(value / 50, 0, 1);
  return interpolateColor(
    [
      "#eef2f4",
      "#9ed8ee",
      "#208dbd",
      "#18a66b",
      "#75df45",
      "#f1e84d",
      "#f0a43c",
      "#ef5c4f",
      "#e85291",
      "#cb45ce",
      "#5d388d",
    ],
    fraction,
  );
}

function interpolateColor(stops, fraction) {
  const scaled = fraction * (stops.length - 1);
  const index = Math.min(Math.floor(scaled), stops.length - 2);
  const local = scaled - index;
  const first = hexToRgb(stops[index]);
  const second = hexToRgb(stops[index + 1]);
  const rgb = first.map((value, channel) =>
    Math.round(value + (second[channel] - value) * local),
  );
  return `rgb(${rgb.join(",")})`;
}

function hexToRgb(value) {
  const parsed = Number.parseInt(value.slice(1), 16);
  return [(parsed >> 16) & 255, (parsed >> 8) & 255, parsed & 255];
}

function formatUtc(value) {
  const date = new Date(value);
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "UTC",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const part = (type) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")} ${part("hour")} UTC`;
}

function formatNumber(value, digits) {
  return value === null || value === undefined || Number.isNaN(Number(value))
    ? "—"
    : Number(value).toFixed(digits);
}

function formatUnit(value, unit, digits) {
  const formatted = formatNumber(value, digits);
  return formatted === "—" ? formatted : `${formatted}${unit}`;
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function exportFilename(extension) {
  if (!currentSounding) {
    return `sounding.${extension}`;
  }
  return [
    currentSounding.stationId,
    archiveDate?.value ?? currentSounding.data.valid_at.slice(0, 10),
    `${currentSounding.cycle}UTC`,
    selectedView,
  ].join("_") + `.${extension}`;
}

async function exportFontData() {
  if (!exportFontDataPromise) {
    exportFontDataPromise = fetch("/static/fonts/MiSans-Sounding.ttf")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Font HTTP ${response.status}`);
        }
        return response.arrayBuffer();
      })
      .then((buffer) => {
        const bytes = new Uint8Array(buffer);
        let binary = "";
        const chunkSize = 0x8000;
        for (let offset = 0; offset < bytes.length; offset += chunkSize) {
          binary += String.fromCharCode(
            ...bytes.subarray(offset, offset + chunkSize),
          );
        }
        return `data:font/ttf;base64,${window.btoa(binary)}`;
      });
  }
  return exportFontDataPromise;
}

async function serializedChart() {
  const clone = profileChart.cloneNode(true);
  clone.setAttribute("xmlns", SVG_NS);
  clone.setAttribute("width", CHART.width);
  clone.setAttribute("height", CHART.height);
  clone.querySelectorAll("[data-export-exclude='true']").forEach(
    (element) => element.remove(),
  );
  const embeddedFont = await exportFontData();
  const style = document.createElementNS(SVG_NS, "style");
  style.textContent = `
    @font-face {
      font-family: "MiSansExport";
      src: url("${embeddedFont}") format("truetype");
      font-style: normal;
      font-weight: 100 900;
    }
    text { font-family: "MiSansExport", sans-serif; }
  `;
  clone.insertBefore(style, clone.firstChild);
  clone.querySelectorAll("text").forEach((element) => {
    element.setAttribute("font-family", "MiSansExport");
  });
  return new XMLSerializer().serializeToString(clone);
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function exportSvg() {
  const blob = new Blob([await serializedChart()], {
    type: "image/svg+xml;charset=utf-8",
  });
  downloadBlob(blob, exportFilename("svg"));
}

async function exportPng() {
  const blob = await rasterizedChartPng();
  downloadBlob(blob, exportFilename("png"));
}

async function rasterizedChartPng() {
  const svgBlob = new Blob([await serializedChart()], {
    type: "image/svg+xml;charset=utf-8",
  });
  const url = URL.createObjectURL(svgBlob);
  try {
    return await new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = CHART.width * 2;
        canvas.height = CHART.height * 2;
        const context = canvas.getContext("2d");
        context.fillStyle = "#ffffff";
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => {
          if (!blob) {
            reject(new Error("PNG export failed"));
            return;
          }
          resolve(blob);
        }, "image/png");
      };
      image.onerror = () => reject(new Error("SVG rasterization failed"));
      image.src = url;
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

const today = toLocalIsoDate(new Date());
if (archiveDate) {
  archiveDate.max = today;
  archiveDate.value = today;
  archiveDate.addEventListener("change", updateArchiveNote);
}
previousDay?.addEventListener("click", () => shiftArchiveDate(-1));
nextDay?.addEventListener("click", () => shiftArchiveDate(1));

cycleButtons.forEach((button) => {
  button.addEventListener("click", () => {
    cycleButtons.forEach((item) => item.classList.remove("is-active"));
    button.classList.add("is-active");
    updateArchiveNote();
  });
});

weatherMapButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedWeatherLayer = button.dataset.mapLayer;
    weatherMapButtons.forEach((item) => {
      item.classList.toggle("is-active", item === button);
    });
    const url = new URL(window.location.href);
    url.searchParams.set("map", selectedWeatherLayer);
    window.history.replaceState({}, "", url);
    void loadWeatherMapProduct();
  });
});

stationDisplayButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedStationDisplay = button.dataset.stationDisplay;
    stationDisplayButtons.forEach((item) => {
      item.classList.toggle("is-active", item === button);
    });
    updateMapStationLabels();
  });
});

viewerButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedView = button.dataset.view;
    viewerButtons.forEach((item) => {
      const isSelected = item === button;
      item.classList.toggle("is-active", isSelected);
      item.setAttribute("aria-selected", String(isSelected));
    });
    renderSoundingSummary();
    renderSelectedView();
  });
});

correctionForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await applySoundingCorrection("manual");
  } catch (error) {
    correctionStatus.textContent = `订正失败：${error.message}`;
  }
});

correctionRealtime?.addEventListener("click", async () => {
  correctionRealtime.disabled = true;
  try {
    await loadHourlyCorrection();
  } catch (error) {
    correctionStatus.textContent = `整点订正失败：${error.message}`;
  } finally {
    correctionRealtime.disabled = false;
  }
});

correctionReset?.addEventListener("click", () => {
  if (!currentSounding) {
    return;
  }
  currentSounding.corrected = null;
  populateCorrectionFields(currentSounding.data);
  renderSoundingSummary();
  renderSelectedView();
});

exportButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    if (!currentSounding || selectedView === "source") {
      return;
    }
    button.disabled = true;
    try {
      if (button.dataset.export === "svg") {
        await exportSvg();
      } else {
        await exportPng();
      }
    } finally {
      button.disabled = false;
    }
  });
});

profileClose?.addEventListener("click", () => {
  profileWorkspace.hidden = true;
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && profileWorkspace && !profileWorkspace.hidden) {
    profileWorkspace.hidden = true;
  }
});

function applyInitialQuery() {
  const parameters = new URLSearchParams(window.location.search);
  const requestedDate = parameters.get("date");
  const requestedCycle = parameters.get("cycle");
  const requestedView = parameters.get("view");
  const requestedStation = parameters.get("station");
  const requestedMap = parameters.get("map");

  if (
    requestedDate &&
    /^\d{4}-\d{2}-\d{2}$/.test(requestedDate) &&
    requestedDate <= archiveDate.max
  ) {
    archiveDate.value = requestedDate;
  }
  if (["00", "12"].includes(requestedCycle)) {
    cycleButtons.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.cycle === requestedCycle);
    });
  }
  if (["skewt", "stuve", "source"].includes(requestedView)) {
    selectedView = requestedView;
    viewerButtons.forEach((button) => {
      const isSelected = button.dataset.view === requestedView;
      button.classList.toggle("is-active", isSelected);
      button.setAttribute("aria-selected", String(isSelected));
    });
  }
  const mapLayers = [
    "composite",
    "surface",
    "850",
    "500",
    "200",
  ];
  if (mapLayers.includes(requestedMap)) {
    selectedWeatherLayer = requestedMap;
    weatherMapButtons.forEach((button) => {
      button.classList.toggle(
        "is-active",
        button.dataset.mapLayer === requestedMap,
      );
    });
  }
  updateArchiveNote();
  if (/^\d{5}$/.test(requestedStation)) {
    stationForm.elements.station.value = requestedStation;
    window.setTimeout(() => stationForm.requestSubmit(), 0);
  }
}

window.CloudyLakeSoundingRenderer = {
  open({ profile, diagnostics = null, stationName, meta = "", rawUrl = null }) {
    currentSounding = {
      data: profile,
      stationId: profile.station_id,
      stationName,
      cycle: new Date(profile.valid_at).getUTCHours().toString().padStart(2, "0"),
      query: "",
      diagnostics,
      corrected: null,
      meta,
      rawUrl,
    };
    renderSelectedView();
    profileWorkspace.hidden = false;
  },
};

if (stationForm && archiveDate) {
  applyInitialQuery();
  loadProjectStatus();
  loadWeatherMapConfig();
}
