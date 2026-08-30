(function () {
  const $ = (selector) => document.querySelector(selector);
  const statusLabel = (value) => ({ fresh: "资料新鲜", degraded: "资料降级", stale: "资料过期", unknown: "状态未知" }[value] || "未配置");
  async function loadHomeStatus() {
    try {
      const [healthResponse, ensembleResponse, cycloneResponse] = await Promise.all([
        fetch("/health/data", { cache: "no-store" }),
        fetch("/api/v1/ensemble/status", { cache: "no-store" }),
        fetch("/api/v1/cyclones/status", { cache: "no-store" }),
      ]);
      const health = healthResponse.ok ? await healthResponse.json() : {};
      const ensemble = ensembleResponse.ok ? await ensembleResponse.json() : {};
      const cyclone = cycloneResponse.ok ? await cycloneResponse.json() : {};
      const label = statusLabel(health.status);
      $("#home-data-status").textContent = label;
      $("#home-readout-status").textContent = label;
      $("#home-readout-time").textContent = health.checked_at ? `检查于 ${new Date(health.checked_at).toLocaleString("zh-CN", { hour12: false })}` : "—";
      $("#latest-time").textContent = health.checked_at ? new Date(health.checked_at).toISOString().slice(0, 16).replace("T", " ") + " UTC" : "—";
      $("#forecast-cache-status").textContent = health.forecast?.status || "—";
      $("#sounding-source-status").textContent = `${health.wis2?.status || "WIS2"} / Wyoming`;
      $("#aifs-status").textContent = statusLabel(ensemble.products?.["aifs-ens"]?.status);
      $("#wn2-status").textContent = statusLabel(ensemble.products?.wn2?.status);
      $("#cyclone-meta").textContent = cyclone.wnc?.status === "available" ? `${cyclone.wnc.members} 成员` : "等待合规 feed";
      if (cyclone.wnc?.status !== "available") $("#cyclone-copy").textContent = "WNC 1000 成员数据尚未配置合规本地 feed；页面保持透明，不用其他模型填充。";
    } catch (error) {
      $("#home-data-status").textContent = "状态读取失败";
      $("#home-readout-status").textContent = "状态读取失败";
    }
  }
  loadHomeStatus();
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches && window.matchMedia("(pointer: fine)").matches) {
    document.addEventListener("pointermove", (event) => {
      document.documentElement.style.setProperty("--grid-x", `${event.clientX / window.innerWidth * 100}%`);
      document.documentElement.style.setProperty("--grid-y", `${event.clientY / window.innerHeight * 100}%`);
    }, { passive: true });
  }
})();
