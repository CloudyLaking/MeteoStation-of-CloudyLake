(() => {
  const $ = (selector) => document.querySelector(selector);
  let latest = null;
  let variable = "temperature_2m";

  const statusText = (status) => ({ available: "本地快照可用", point_available: "按需可用", invalid: "快照无效" })[status] || "等待资料";

  function linePath(values, x, y) {
    let d = "";
    values.forEach((value, index) => {
      if (value == null || !Number.isFinite(Number(value))) return;
      d += `${d ? "L" : "M"}${x(index).toFixed(1)},${y(Number(value)).toFixed(1)}`;
    });
    return d;
  }

  function bandPath(low, high, x, y) {
    const upper = high.map((value, index) => value == null ? null : [x(index), y(Number(value))]).filter(Boolean);
    const lower = low.map((value, index) => value == null ? null : [x(index), y(Number(value))]).filter(Boolean).reverse();
    if (!upper.length || !lower.length) return "";
    return `M${upper.concat(lower).map((point) => `${point[0].toFixed(1)},${point[1].toFixed(1)}`).join("L")}Z`;
  }

  function renderChart() {
    if (!latest?.variables?.[variable]) return;
    const product = latest.variables[variable];
    const stats = product.statistics;
    const all = product.members.flat().filter((value) => value != null && Number.isFinite(Number(value))).map(Number);
    if (!all.length) return;
    let min = Math.min(...all), max = Math.max(...all);
    const padding = Math.max((max - min) * .08, 1); min -= padding; max += padding;
    const width = 1120, height = 430, margin = { left: 58, right: 18, top: 18, bottom: 42 };
    const x = (index) => margin.left + index / Math.max(1, latest.times.length - 1) * (width - margin.left - margin.right);
    const y = (value) => margin.top + (max - value) / (max - min) * (height - margin.top - margin.bottom);
    const yTicks = Array.from({ length: 6 }, (_, index) => min + (max - min) * index / 5);
    const xTicks = Array.from({ length: 7 }, (_, index) => Math.round((latest.times.length - 1) * index / 6));
    const grid = yTicks.map((value) => `<line x1="${margin.left}" y1="${y(value)}" x2="${width-margin.right}" y2="${y(value)}"/><text x="${margin.left-9}" y="${y(value)+4}" text-anchor="end">${value.toFixed(product.unit.includes("°") ? 0 : 1)}</text>`).join("");
    const labels = xTicks.map((index) => `<text x="${x(index)}" y="${height-12}" text-anchor="middle">${latest.times[index].slice(5, 16).replace("T", " ")}</text>`).join("");
    const members = product.members.map((row) => `<path class="member" d="${linePath(row,x,y)}"/>`).join("");
    $("#ensemble-chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${product.label}集合时间序列"><g class="chart-grid">${grid}${labels}</g><path class="band outer" d="${bandPath(stats.p10,stats.p90,x,y)}"/><path class="band inner" d="${bandPath(stats.p25,stats.p75,x,y)}"/><g>${members}</g><path class="median" d="${linePath(stats.median,x,y)}"/></svg>`;
    $("#ensemble-chart-title").textContent = `${product.label} · ${product.unit}`;
  }

  function installVariableTabs() {
    const box = $("#ensemble-vars");
    if (!latest.variables[variable]) variable = Object.keys(latest.variables)[0];
    box.replaceChildren(...Object.entries(latest.variables).map(([key, item]) => {
      const button = document.createElement("button"); button.type = "button"; button.textContent = item.label; button.className = key === variable ? "is-active" : "";
      button.addEventListener("click", () => { variable = key; box.querySelectorAll("button").forEach((candidate) => candidate.classList.toggle("is-active", candidate === button)); renderChart(); });
      return button;
    }));
  }

  async function loadStatus() {
    try {
      const response = await fetch("/api/v1/ensemble/status", { cache: "no-store" }); const data = await response.json();
      $("#ensemble-status").replaceChildren(...Object.values(data.products || {}).map((product, index) => {
        const article = document.createElement("article"); article.className = `luna-status-panel${index ? " luna-status-panel--violet" : ""}`;
        article.innerHTML = `<div class="panel-rule"><span>${product.label}</span><b>${statusText(product.status)}</b></div><h2>${product.members} 个成员 · 360 小时</h2><p>${product.detail || "已校验的本地派生产品。"}</p><a href="${product.source_url}" target="_blank" rel="noopener">查看模型资料 →</a>`;
        return article;
      }));
    } catch (_) { $("#ensemble-status").textContent = "模型目录暂不可用"; }
  }

  $("#ensemble-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button"); button.disabled = true; button.textContent = "正在读取…";
    $("#ensemble-chart").innerHTML = '<p class="ensemble-empty">正在连接集合资料源并计算分位数…</p>';
    try {
      const model = $("#ensemble-model").value, lat = $("#ensemble-lat").value, lon = $("#ensemble-lon").value;
      const response = await fetch(`/api/v1/ensemble/point?model=${encodeURIComponent(model)}&lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || "资料读取失败"); latest = data;
      $("#ensemble-chart-model").textContent = model === "aifs-ens" ? "AIFS ENS" : "WeatherNext 2";
      $("#ensemble-chart-meta").textContent = `${data.latitude.toFixed(2)}°, ${data.longitude.toFixed(2)}° · ${data.members} 成员 · UTC · ${data.cache === "hit" ? "缓存" : "实时获取"}`;
      installVariableTabs(); renderChart();
    } catch (error) { $("#ensemble-chart").innerHTML = `<p class="ensemble-empty is-error">${error.message}</p>`; }
    finally { button.disabled = false; button.textContent = "读取原生集合"; }
  });
  loadStatus();
})();
