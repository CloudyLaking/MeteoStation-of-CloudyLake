const form = document.querySelector("#forecast-form");
const locationInput = document.querySelector("#forecast-location");
const dateInput = document.querySelector("#forecast-date");
const status = document.querySelector("#forecast-status");
const options = document.querySelector("#forecast-location-options");
const section = document.querySelector("#surface-forecast-section");
const title = document.querySelector("#surface-forecast-title");
const source = document.querySelector("#surface-forecast-source");
const chart = document.querySelector("#point-forecast-chart");
const pointMapElement = document.querySelector("#point-forecast-world-map");
const pointCoordinate = document.querySelector("#point-world-coordinate");

let pointMap = null;
let pointMarker = null;

dateInput.value = new Date().toISOString().slice(0, 10);

function setForecastPoint(latitude, longitude, { move = true, updateInput = true } = {}) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || !pointMap) return;
  if (pointMarker) pointMarker.setLatLng([latitude, longitude]);
  else {
    pointMarker = window.L.circleMarker([latitude, longitude], {
      radius: 6,
      color: "#ffffff",
      weight: 2,
      fillColor: "#126e68",
      fillOpacity: 1,
    }).addTo(pointMap);
  }
  if (move) pointMap.setView([latitude, longitude], Math.max(pointMap.getZoom(), 5));
  if (updateInput) locationInput.value = `${latitude.toFixed(4)},${longitude.toFixed(4)}`;
  if (pointCoordinate) {
    pointCoordinate.textContent = `已选择 ${latitude.toFixed(4)}°, ${longitude.toFixed(4)}° · 可继续移动地图选点`;
  }
}

function initializePointMap() {
  if (!pointMapElement || !window.L) {
    if (pointCoordinate) pointCoordinate.textContent = "地图组件暂未加载，仍可直接输入站号、地名或经纬度。";
    return;
  }
  pointMap = window.L.map(pointMapElement, {
    worldCopyJump: true,
    minZoom: 2,
    maxZoom: 10,
    scrollWheelZoom: true,
    wheelPxPerZoomLevel: 140,
    zoomSnap: 0.5,
    zoomDelta: 0.5,
    touchZoom: true,
  }).setView([28, 105], 2);
  window.L.control.attribution({ prefix: false }).addAttribution("本地站点目录 · 无外部瓦片底图").addTo(pointMap);
  pointMap.on("click", (event) => {
    setForecastPoint(event.latlng.lat, event.latlng.lng, { move: false, updateInput: true });
  });
  setForecastPoint(31.65, 121.75, { move: false, updateInput: false });
}

initLocationSuggest(locationInput, options, {
  onPick: (item) => {
    setForecastPoint(item.latitude, item.longitude, { updateInput: false });
    form.requestSubmit();
  },
});

window.addEventListener("DOMContentLoaded", initializePointMap);

function svg(tag, attributes = {}, text = "") {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, String(value));
  }
  if (text) element.textContent = text;
  return element;
}

function values(points, key) {
  return points
    .map((point) => Number(point[key]))
    .filter((value) => Number.isFinite(value));
}

function paddedExtent(input, ratio = 0.15) {
  if (!input.length) return [0, 1];
  const minimum = Math.min(...input);
  const maximum = Math.max(...input);
  const span = Math.max(maximum - minimum, 1);
  return [minimum - span * ratio, maximum + span * ratio];
}

function pathFor(points, key, x, y) {
  let started = false;
  return points
    .map((point) => {
      const value = Number(point[key]);
      if (!Number.isFinite(value)) return "";
      const command = started ? "L" : "M";
      started = true;
      return `${command}${x(point.step_hours).toFixed(1)},${y(value).toFixed(1)}`;
    })
    .join(" ");
}

function compass(degrees) {
  if (!Number.isFinite(Number(degrees))) return "—";
  const directions = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
  ];
  return directions[Math.round(Number(degrees) / 22.5) % 16];
}

function renderForecastDeprecated(data, model) {
  const points = (data.points || [])
    .filter((point) => point.step_hours > 0 && point.step_hours <= 72)
    .sort((left, right) => left.step_hours - right.step_hours);
  if (!points.length) return false;

  chart.replaceChildren();
  const left = 70;
  const right = 970;
  const width = right - left;
  const x = (step) => left + (Number(step) / 72) * width;
  const panels = {
    temperature: [62, 250],
    pressure: [294, 382],
    precipitation: [426, 500],
    cloud: [548, 600],
  };

  chart.appendChild(svg("rect", { width: 1000, height: 650, fill: "#fff" }));
  chart.appendChild(svg("text", {
    x: 972,
    y: 22,
    "text-anchor": "end",
    "font-size": 12,
    "font-weight": 700,
    fill: "#126e68",
  }, "@CloudyLake"));

  for (let hour = 0; hour <= 72; hour += 6) {
    const position = x(hour);
    const dayBoundary = hour % 24 === 0;
    chart.appendChild(svg("line", {
      x1: position,
      y1: panels.temperature[0],
      x2: position,
      y2: panels.cloud[1],
      stroke: dayBoundary ? "#a9aaa5" : "#dfddd7",
      "stroke-width": dayBoundary ? 1.5 : 1,
      "stroke-dasharray": dayBoundary ? "0" : "3 4",
    }));
    if (hour > 0) {
      chart.appendChild(svg("text", {
        x: position,
        y: 624,
        "text-anchor": "middle",
        "font-size": 11,
        fill: "#58666b",
      }, `+${hour}h`));
    }
  }

  [1, 2, 3].forEach((day) => {
    chart.appendChild(svg("text", {
      x: x((day - 0.5) * 24),
      y: 642,
      "text-anchor": "middle",
      "font-size": 12,
      "font-weight": 650,
      fill: "#233d47",
    }, `DAY ${day}`));
  });

  const temperatureValues = [
    ...values(points, "temperature_2m_c"),
    ...values(points, "dewpoint_2m_c"),
  ];
  const [temperatureMin, temperatureMax] = paddedExtent(temperatureValues);
  const yTemperature = (value) =>
    panels.temperature[1] -
    ((value - temperatureMin) / (temperatureMax - temperatureMin)) *
      (panels.temperature[1] - panels.temperature[0]);

  for (let index = 0; index <= 4; index += 1) {
    const value =
      temperatureMin + ((temperatureMax - temperatureMin) * index) / 4;
    const y = yTemperature(value);
    chart.appendChild(svg("line", {
      x1: left, y1: y, x2: right, y2: y, stroke: "#ece9e3",
    }));
    chart.appendChild(svg("text", {
      x: left - 9, y: y + 4, "text-anchor": "end",
      "font-size": 11, fill: "#657178",
    }, `${value.toFixed(0)}°`));
  }
  chart.appendChild(svg("text", {
    x: left, y: 35, "font-size": 14, "font-weight": 700, fill: "#243b46",
  }, "TEMPERATURE / DEW POINT"));
  chart.appendChild(svg("path", {
    d: pathFor(points, "temperature_2m_c", x, yTemperature),
    fill: "none", stroke: "#df2727", "stroke-width": 3,
  }));
  chart.appendChild(svg("path", {
    d: pathFor(points, "dewpoint_2m_c", x, yTemperature),
    fill: "none", stroke: "#197d70", "stroke-width": 3,
  }));
  for (const point of points) {
    for (const [key, colour] of [
      ["temperature_2m_c", "#df2727"],
      ["dewpoint_2m_c", "#197d70"],
    ]) {
      const value = Number(point[key]);
      if (!Number.isFinite(value)) continue;
      chart.appendChild(svg("circle", {
        cx: x(point.step_hours),
        cy: yTemperature(value),
        r: 3.5,
        fill: colour,
      }));
    }
  }

  const [pressureMin, pressureMax] = paddedExtent(
    values(points, "mslp_hpa"),
    0.25,
  );
  const yPressure = (value) =>
    panels.pressure[1] -
    ((value - pressureMin) / (pressureMax - pressureMin)) *
      (panels.pressure[1] - panels.pressure[0]);
  chart.appendChild(svg("text", {
    x: left, y: 278, "font-size": 14, "font-weight": 700, fill: "#243b46",
  }, "MEAN SEA LEVEL PRESSURE"));
  chart.appendChild(svg("path", {
    d: pathFor(points, "mslp_hpa", x, yPressure),
    fill: "none", stroke: "#225fa8", "stroke-width": 2.5,
  }));
  for (const point of points) {
    const value = Number(point.mslp_hpa);
    if (!Number.isFinite(value)) continue;
    chart.appendChild(svg("circle", {
      cx: x(point.step_hours),
      cy: yPressure(value),
      r: 3,
      fill: "#225fa8",
    }));
  }

  const rainMaximum = Math.max(...values(points, "total_precipitation_mm"), 0.1);
  const nominalCadence = model === "aifs" ? 6 : 3;
  const barWidth = Math.max(width * nominalCadence / 72 - 2, 5);
  chart.appendChild(svg("text", {
    x: left, y: 412, "font-size": 14, "font-weight": 700, fill: "#243b46",
  }, "PRECIPITATION / WIND"));
  for (const point of points) {
    const amount = Number(point.total_precipitation_mm);
    if (Number.isFinite(amount) && amount > 0) {
      const height =
        (amount / rainMaximum) *
        (panels.precipitation[1] - panels.precipitation[0]);
      chart.appendChild(svg("rect", {
        x: x(point.step_hours) - barWidth / 2,
        y: panels.precipitation[1] - height,
        width: barWidth,
        height,
        fill: "#f2c94c",
        opacity: 0.65,
      }));
    }
    if (point.step_hours % 6 === 0) {
      chart.appendChild(svg("text", {
        x: x(point.step_hours),
        y: panels.precipitation[0] + 15,
        "text-anchor": "middle",
        "font-size": 9.5,
        fill: "#4f5c62",
      }, `${compass(point.wind_direction_10m_deg)} ${Number(
        point.wind_speed_10m_ms ?? 0,
      ).toFixed(1)}`));
    }
  }

  chart.appendChild(svg("text", {
    x: left, y: 535, "font-size": 14, "font-weight": 700, fill: "#243b46",
  }, "TOTAL CLOUD COVER"));
  for (const point of points) {
    const cloud = Math.max(
      0,
      Math.min(100, Number(point.total_cloud_cover_pct ?? 0)),
    );
    chart.appendChild(svg("rect", {
      x: x(point.step_hours) - barWidth / 2,
      y: panels.cloud[0],
      width: barWidth,
      height: panels.cloud[1] - panels.cloud[0],
      fill: "#176f68",
      opacity: 0.06 + cloud / 115,
    }));
  }
  chart.appendChild(svg("text", {
    x: left - 9, y: panels.cloud[0] + 5, "text-anchor": "end",
    "font-size": 10, fill: "#657178",
  }, "100%"));
  chart.appendChild(svg("text", {
    x: left - 9, y: panels.cloud[1], "text-anchor": "end",
    "font-size": 10, fill: "#657178",
  }, "0%"));

  const legend = [
    ["#df2727", "Temperature"],
    ["#197d70", "Dew point"],
    ["#225fa8", "MSLP"],
    ["#f2c94c", "Precipitation"],
    ["#176f68", "Cloud"],
  ];
  legend.forEach(([colour, label], index) => {
    const legendX = 500 + index * 92;
    chart.appendChild(svg("line", {
      x1: legendX, y1: 30, x2: legendX + 18, y2: 30,
      stroke: colour, "stroke-width": 3,
    }));
    chart.appendChild(svg("text", {
      x: legendX + 22, y: 34, "font-size": 9.5, fill: "#4f5c62",
    }, label));
  });
  return true;
}

function renderForecast(data, model) {
  const rawPoints = (data.points || [])
    .filter((point) => point.step_hours > 0 && point.step_hours <= 72)
    .sort((left, right) => left.step_hours - right.step_hours);
  if (!rawPoints.length) return false;
  const points = rawPoints.map((point) => ({
    time: point.valid_at,
    temperature: point.temperature_2m_c,
    dewpoint: point.dewpoint_2m_c,
    apparent: window.CloudyLakeWeatherSeriesRenderer.apparentTemperature(
      point.temperature_2m_c,
      point.relative_humidity_2m_pct,
    ),
    humidity: point.relative_humidity_2m_pct,
    pressure: point.surface_pressure_hpa,
    seaLevelPressure: point.mslp_hpa,
    precipitation: point.total_precipitation_mm,
    windSpeed: point.wind_speed_10m_ms,
    windDirection: point.wind_direction_10m_deg,
  }));
  const cadence = model === "aifs" ? 6 : 3;
  const accumulated = (count) => points.slice(0, count).reduce(
    (sum, point) => sum + Math.max(0, Number(point.precipitation) || 0),
    0,
  );
  const meta = payload.meta || {};
  const ageText = Number.isFinite(Number(meta.data_age_hours))
    ? `，资料年龄 ${Number(meta.data_age_hours).toFixed(1)} h`
    : "";
  const degradedText = meta.degraded ? "（降级资料）" : "";
  window.CloudyLakeWeatherSeriesRenderer.render(chart, {
    title: `${data.station_name} · ${model.toUpperCase()} 72h单点预报`,
    locationLine: `${Number(data.latitude).toFixed(2)}°N  ${Number(data.longitude).toFixed(2)}°E`,
    timeLine: `起报时次: ${new Date(data.initialized_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false })}${ageText}${degradedText}`,
    points,
    includeDateLabels: true,
    accumulationLines: [
      `未来24 小时累计降水量: ${accumulated(Math.round(24 / cadence)).toFixed(1)} mm`,
      `未来48h累计降水量: ${accumulated(Math.round(48 / cadence)).toFixed(1)} mm`,
      `未来72h累计降水量: ${accumulated(points.length).toFixed(1)} mm`,
    ],
  });
  return true;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const location = locationInput.value.trim();
  if (!location) {
    status.textContent = "请输入国家站号、站名或“纬度,经度”。";
    return;
  }
  const model =
    document.querySelector('input[name="model"]:checked')?.value || "ifs";
  const cycle =
    document.querySelector('input[name="cycle"]:checked')?.value || "00";
  const query = new URLSearchParams({
    date: dateInput.value,
    cycle,
    model,
    horizon: "72",
  });
  const requestedInitialization = `${dateInput.value}T${cycle}:00:00Z`;
  status.textContent = `正在读取 ${model.toUpperCase()} 三天单点预报……`;
  section.hidden = true;

  try {
    const response = await fetch(
      `/api/v1/forecast/surface/${encodeURIComponent(location)}?${query}`,
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
    if (!renderForecast(payload, model)) {
      throw new Error("所选起报时次尚无完整的未来三天预报");
    }
    title.textContent =
      `${payload.station_name} · ${model.toUpperCase()} 三天预报`;
    source.textContent =
      `${payload.source} · ${payload.latitude.toFixed(3)}, ${payload.longitude.toFixed(3)}`;
    section.hidden = false;
    const actualInitialization = new Date(payload.initialized_at);
    const meta = payload.meta || {};
    if (meta.degraded) {
      status.textContent = `资料降级：当前显示 ${payload.initialized_at.slice(0, 16).replace("T", " ")} UTC 起报的完整周期（年龄 ${Number(meta.data_age_hours).toFixed(1)} h），最新起报尚在准备或校验中。`;
    } else if (
      Number.isFinite(actualInitialization.valueOf())
      && payload.initialized_at !== requestedInitialization
    ) {
      dateInput.value = actualInitialization.toISOString().slice(0, 10);
      const actualCycle = String(actualInitialization.getUTCHours()).padStart(2, "0");
      const actualCycleInput = [...form.querySelectorAll('input[name="cycle"]')]
        .find((input) => input.value === actualCycle);
      if (actualCycleInput) actualCycleInput.checked = true;
      status.textContent = `所选起报已退出服务器缓存，已自动使用 ${dateInput.value} ${actualCycle} UTC 的最近完整资料。`;
    } else {
      status.textContent = "";
    }
  } catch (error) {
    status.textContent = `单点预报读取失败：${error.message}`;
  }
});

const initialForecastQuery = new URLSearchParams(window.location.search);
if (initialForecastQuery.get("station")) {
  locationInput.value = initialForecastQuery.get("station");
  if (initialForecastQuery.get("date")) dateInput.value = initialForecastQuery.get("date");
  if (initialForecastQuery.get("cycle")) {
    const cycleInput = [...form.querySelectorAll('input[name="cycle"]')]
      .find((input) => input.value === initialForecastQuery.get("cycle"));
    if (cycleInput) cycleInput.checked = true;
  }
  if (initialForecastQuery.get("model")) {
    const modelInput = [...form.querySelectorAll('input[name="model"]')]
      .find((input) => input.value === initialForecastQuery.get("model"));
    if (modelInput) modelInput.checked = true;
  }
  window.setTimeout(() => form.requestSubmit(), 0);
}
