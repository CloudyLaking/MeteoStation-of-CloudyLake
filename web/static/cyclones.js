(() => {
  const $ = (selector) => document.querySelector(selector);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);

  function renderMap(systems) {
    const width = 1120, height = 500;
    const x = (lon) => (Number(lon) + 180) / 360 * width;
    const y = (lat) => (90 - Number(lat)) / 180 * height;
    const meridians = [-120,-60,0,60,120].map((lon) => `<line x1="${x(lon)}" y1="0" x2="${x(lon)}" y2="${height}"/><text x="${x(lon)+5}" y="${height-8}">${lon}°</text>`).join("");
    const parallels = [-60,-30,0,30,60].map((lat) => `<line x1="0" y1="${y(lat)}" x2="${width}" y2="${y(lat)}"/><text x="7" y="${y(lat)-6}">${lat}°</text>`).join("");
    const marks = systems.map((system) => `<g class="cyclone-mark" transform="translate(${x(system.longitude)},${y(system.latitude)})"><circle r="9"/><path d="M-14,0C-8,-10 1,-10 4,-4C8,3 1,7 -5,4M14,0C8,10 -1,10 -4,4C-8,-3 -1,-7 5,-4"/><text x="15" y="-12">${escapeHtml(system.id)} ${escapeHtml(system.name || "")}</text></g>`).join("");
    $("#cyclone-map").innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true"><g class="cyclone-graticule">${meridians}${parallels}</g><path class="cyclone-equator" d="M0 ${y(0)}H${width}"/><g>${marks}</g></svg>`;
  }

  async function loadRegistry() {
    try {
      const response = await fetch("/api/v1/cyclones/current", { cache: "no-store" }); const data = await response.json();
      const systems = data.systems || []; renderMap(systems);
      const sourceLabel = String(data.source_role || "").startsWith("GDACS") ? "GDACS 全球态势参考" : "NRL ATCF 警报参考";
      $("#cyclone-registry-meta").textContent = systems.length ? `${systems.length} 个系统 · ${data.valid_at.slice(0,16).replace("T"," ")} UTC · ${sourceLabel}` : "当前没有可显示的官方警报系统";
      $("#cyclone-system-list").replaceChildren(...systems.map((system) => {
        const item = document.createElement("article");
        item.innerHTML = `<b>${escapeHtml(system.id)}</b><strong>${escapeHtml(system.name || "未命名")}</strong><span>${Number(system.latitude).toFixed(1)}°, ${Number(system.longitude).toFixed(1)}°</span><span>${system.maximum_wind_ms == null ? "风速缺测" : `${system.maximum_wind_ms} m/s`}</span>`;
        return item;
      }));
    } catch (_) { $("#cyclone-registry-meta").textContent = "官方参考层暂不可用"; renderMap([]); }
  }

  async function loadWnc() {
    try {
      const response = await fetch("/api/v1/cyclones/status", { cache: "no-store" }); const data = await response.json(); const item = data.wnc || {};
      const article = document.createElement("article"); article.className = "luna-status-panel luna-status-panel--violet";
      const ready = item.status === "available";
      article.innerHTML = `<div class="panel-rule"><span>${item.label || "WeatherNext Cyclones"}</span><b>${ready ? "成员可用" : "等待合规数据"}</b></div><h2>${ready ? item.members : item.member_target || 1000} 成员</h2><p>${ready ? "已读取真实 WNC 成员派生快照。" : "分析框架已经就绪；尚未取得可公开展示的 WNC 成员 feed，因此不生成虚假轨迹。"}</p><a href="${item.weather_lab_url || "https://www.weatherlab.ai/"}" target="_blank" rel="noopener">查看官方 Weather Lab →</a>`;
      $("#cyclone-status").replaceChildren(article);
      $("#cluster-count").textContent = ready ? "待计算" : "数据待接入";
    } catch (_) { $("#cyclone-status").textContent = "WNC 状态暂不可用"; }
  }
  async function searchHistory(query) {
    const results = $("#history-search-results"); results.textContent = "正在读取 IBTrACS 索引…";
    try {
      const response = await fetch(`/api/v1/history/storms?q=${encodeURIComponent(query)}&limit=20`); const data = await response.json();
      if (data.status !== "available") throw new Error("历史索引尚未安装");
      results.replaceChildren(...data.storms.map((storm) => {
        const button = document.createElement("button"); button.type = "button";
        button.innerHTML = `<b>${escapeHtml(storm.name)}</b><span>${storm.season} · ${escapeHtml(storm.sid)} · ${storm.max_wind_kt ?? "—"} kt</span>`;
        button.addEventListener("click", () => loadAnalogs(storm.sid, storm.name)); return button;
      }));
      if (!data.storms.length) results.textContent = "没有找到匹配台风";
    } catch (error) { results.textContent = error.message; }
  }
  async function loadAnalogs(sid, name) {
    const target = $("#history-analog-results"); target.textContent = `正在计算 ${name} 的相似案例…`;
    try {
      const response = await fetch(`/api/v1/history/analogs/${encodeURIComponent(sid)}`); const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "计算失败");
      target.innerHTML = `<h3>${escapeHtml(name)} 的相似案例</h3>`;
      const list = document.createElement("div");
      data.analogs.forEach((item) => {
        const article = document.createElement("article"); const components = item.components;
        article.innerHTML = `<strong>${escapeHtml(item.name)} · ${item.season}</strong><b>${Math.round(item.score*100)} 分</b><span>路径 ${Math.round(components.path*100)} · 强度 ${Math.round(components.intensity*100)} · 季节 ${Math.round(components.season*100)}</span><small>平均轨迹距离 ${item.track_distance_km} km</small><a href="${item.era5_link}">打开同期 ERA5 →</a>`;
        list.append(article);
      }); target.append(list);
    } catch (error) { target.textContent = error.message; }
  }
  const historyForm = $("#history-search-form");
  if (historyForm) historyForm.addEventListener("submit", (event) => { event.preventDefault(); searchHistory($("#history-search").value); });
  loadRegistry(); loadWnc();
})();
