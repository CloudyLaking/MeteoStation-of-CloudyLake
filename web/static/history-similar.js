(() => {
  const $ = (selector) => document.querySelector(selector);
  const escapeHtml = (value) => String(value ?? "").replace(
    /[&<>"']/g,
    (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character],
  );

  async function loadAnalogs(sid, name) {
    const target = $("#history-analog-results");
    target.textContent = `正在计算 ${name} 的相似案例…`;
    try {
      const response = await fetch(
        `/api/v1/history/analogs/${encodeURIComponent(sid)}`,
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "计算失败");
      target.innerHTML = `<h3>${escapeHtml(name)} 的相似案例</h3>`;
      const list = document.createElement("div");
      data.analogs.forEach((item) => {
        const article = document.createElement("article");
        const components = item.components;
        article.innerHTML = `<strong>${escapeHtml(item.name)} · ${item.season}</strong><b>${Math.round(item.score * 100)} 分</b><span>路径 ${Math.round(components.path * 100)} · 强度 ${Math.round(components.intensity * 100)} · 季节 ${Math.round(components.season * 100)}</span><small>平均轨迹距离 ${item.track_distance_km} 千米</small><a href="${item.era5_link}">打开同期历史再分析 →</a>`;
        list.append(article);
      });
      target.append(list);
    } catch (error) {
      target.textContent = error.message;
    }
  }

  async function searchHistory(query) {
    const results = $("#history-search-results");
    results.textContent = "正在读取历史台风索引…";
    try {
      const response = await fetch(
        `/api/v1/history/storms?q=${encodeURIComponent(query)}&limit=20`,
      );
      const data = await response.json();
      if (data.status !== "available") throw new Error("历史索引尚未安装");
      results.replaceChildren(
        ...data.storms.map((storm) => {
          const button = document.createElement("button");
          button.type = "button";
          button.innerHTML = `<b>${escapeHtml(storm.name)}</b><span>${storm.season} · ${escapeHtml(storm.sid)} · 最大风速 ${storm.max_wind_kt ?? "—"} 节</span>`;
          button.addEventListener(
            "click",
            () => loadAnalogs(storm.sid, storm.name),
          );
          return button;
        }),
      );
      if (!data.storms.length) results.textContent = "没有找到匹配台风";
    } catch (error) {
      results.textContent = error.message;
    }
  }

  $("#history-search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    searchHistory($("#history-search").value);
  });
})();

