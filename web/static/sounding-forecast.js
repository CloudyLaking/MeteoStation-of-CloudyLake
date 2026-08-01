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

let latestForecast = null;

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

forecastLocation.addEventListener("input", async () => {
  const query = forecastLocation.value.trim();
  if (query.length < 2 || query.includes(",") || query.includes("，")) return;
  try {
    const response = await fetch(
      `/api/v1/stations/search?q=${encodeURIComponent(query)}&limit=8`,
    );
    if (!response.ok) return;
    const data = await response.json();
    forecastOptions.replaceChildren();
    for (const station of data.stations || []) {
      const option = document.createElement("option");
      option.value = station.wmo_id;
      option.label =
        `${station.display_name} · ` +
        `${station.latitude.toFixed(2)},${station.longitude.toFixed(2)}`;
      forecastOptions.appendChild(option);
    }
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
      throw new Error(payload.detail || `HTTP ${response.status}`);
    }
    latestForecast = payload;
    const validAt = payload.profile.valid_at.slice(0, 16).replace("T", " ");
    forecastTitle.textContent =
      `${payload.station_name} · ${model.toUpperCase()} +${payload.step_hours} h`;
    forecastSource.textContent =
      `${validAt} UTC · ${payload.profile.source} · ` +
      `${payload.profile.station_latitude.toFixed(3)}, ` +
      `${payload.profile.station_longitude.toFixed(3)}`;
    forecastSection.hidden = false;
    forecastStatus.textContent = "";
    openProfile(payload);
  } catch (error) {
    forecastStatus.textContent = `探空预报读取失败：${error.message}`;
  }
});

const params = new URLSearchParams(window.location.search);
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
