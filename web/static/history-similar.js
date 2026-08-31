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

  const trackColors = ["#7d6898", "#126e68", "#c8795d", "#b5a89c", "#d59a52"];

  function unwrapTrack(points) {
    const output = [];
    let previous = null;
    points.forEach((point) => {
      let longitude = Number(point.lon);
      if (previous !== null) {
        while (longitude - previous > 180) longitude -= 360;
        while (longitude - previous < -180) longitude += 360;
      }
      output.push({ ...point, longitude, latitude: Number(point.lat) });
      previous = longitude;
    });
    return output;
  }

  function renderTrackMap(data) {
    const targetTrack = unwrapTrack(data.target.points || []);
    if (targetTrack.length < 2) return;
    const targetMean = targetTrack.reduce((sum, point) => sum + point.longitude, 0) / targetTrack.length;
    const tracks = [{ name: `${data.target.name} · ${data.target.season}`, points: targetTrack, target: true }];
    data.analogs.slice(0, 5).forEach((item, index) => {
      const points = unwrapTrack(item.points || []);
      if (!points.length) return;
      const mean = points.reduce((sum, point) => sum + point.longitude, 0) / points.length;
      const shift = Math.round((targetMean - mean) / 360) * 360;
      tracks.push({ name: `${item.name} · ${item.season}`, points: points.map((point) => ({ ...point, longitude: point.longitude + shift })), color: trackColors[index] });
    });
    const all = tracks.flatMap((track) => track.points);
    const rawMinLon = Math.min(...all.map((point) => point.longitude));
    const rawMaxLon = Math.max(...all.map((point) => point.longitude));
    const rawMinLat = Math.min(...all.map((point) => point.latitude));
    const rawMaxLat = Math.max(...all.map((point) => point.latitude));
    const lonPad = Math.max(4, (rawMaxLon - rawMinLon) * 0.08);
    const latPad = Math.max(3, (rawMaxLat - rawMinLat) * 0.12);
    const minLon = rawMinLon - lonPad, maxLon = rawMaxLon + lonPad;
    const minLat = Math.max(-90, rawMinLat - latPad), maxLat = Math.min(90, rawMaxLat + latPad);
    const width = 960, height = 440, pad = 34;
    const x = (lon) => pad + (lon - minLon) / Math.max(1, maxLon - minLon) * (width - pad * 2);
    const y = (lat) => height - pad - (lat - minLat) / Math.max(1, maxLat - minLat) * (height - pad * 2);
    const grid = [];
    for (let lon = Math.ceil(minLon / 10) * 10; lon <= maxLon; lon += 10) grid.push(`<path d="M${x(lon).toFixed(1)} ${pad}V${height-pad}"/><text x="${(x(lon)+4).toFixed(1)}" y="${height-10}">${((lon + 540) % 360) - 180}°</text>`);
    for (let lat = Math.ceil(minLat / 10) * 10; lat <= maxLat; lat += 10) grid.push(`<path d="M${pad} ${y(lat).toFixed(1)}H${width-pad}"/><text x="5" y="${(y(lat)-4).toFixed(1)}">${lat}°</text>`);
    const paths = tracks.map((track, index) => {
      const points = track.points.map((point) => `${x(point.longitude).toFixed(1)},${y(point.latitude).toFixed(1)}`).join(" ");
      const color = track.target ? "#9b514a" : track.color;
      const last = track.points.at(-1);
      return `<g><polyline points="${points}" fill="none" stroke="${color}" stroke-width="${track.target ? 4 : 2}" vector-effect="non-scaling-stroke"/><circle cx="${x(track.points[0].longitude).toFixed(1)}" cy="${y(track.points[0].latitude).toFixed(1)}" r="${track.target ? 4 : 3}" fill="${color}"/><path d="M${(x(last.longitude)-4).toFixed(1)} ${(y(last.latitude)-4).toFixed(1)}l8 8m0-8l-8 8" stroke="${color}" stroke-width="2"/></g>`;
    }).join("");
    $("#history-track-map").innerHTML = `<svg viewBox="0 0 ${width} ${height}" aria-hidden="true"><g class="history-track-grid">${grid.join("")}</g>${paths}</svg>`;
    $("#history-track-legend").innerHTML = tracks.map((track) => `<span><i style="background:${track.target ? "#9b514a" : track.color}"></i>${escapeHtml(track.name)}</span>`).join("");
    $("#history-track-view").hidden = false;
  }

  async function loadAnalogs(sid, name) {
    const target = $("#history-analog-results");
    target.textContent = `正在计算 ${name} 的相似案例…`;
    try {
      const response = await fetch(
        `/api/v1/history/analogs/${encodeURIComponent(sid)}`,
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "计算失败");
      renderTrackMap(data);
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
