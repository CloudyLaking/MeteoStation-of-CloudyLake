/* Shared shell: language preference, status strip, navigation and scroll state. */
(function () {
  const dictionary = {
    "nav.home": ["首页", "Home"], "nav.live": ["实况", "Live"], "nav.forecast": ["预报", "Forecast"],
    "nav.sounding": ["探空", "Soundings"], "nav.cyclones": ["台风", "Cyclones"], "nav.history": ["历史", "History"], "nav.tools": ["工具", "Tools"],
    "home.kicker": ["真实资料 · 可追溯 · 可解释", "Observed data · Traceable · Explainable"],
    "home.title": ["从观测到集合，读懂天气的不确定性", "From observations to ensembles, understand uncertainty"],
    "home.intro": ["把探空、地面实况、模式背景和集合信号放在同一张清晰的时间轴上。每个产品都标明来源、时效、质量和回退状态。", "Bring soundings, surface observations, model fields and ensemble signals onto one clear timeline. Every product states its source, validity, quality and fallback state."],
    "home.search_label": ["搜索城市、站号或经纬度", "Search a city, station or coordinates"], "home.search_placeholder": ["例如：上海 / 58362 / 31.2,121.5", "e.g. Shanghai / 58362 / 31.2,121.5"], "home.search_button": ["进入工作台", "Open workspace"],
    "home.readout_label": ["资料总览", "Data overview"], "home.health_link": ["查看健康检查 →", "View health →"],
    "home.latest_label": ["最新资料", "Latest data"], "home.latest_title": ["今天的天气，从可靠的观测开始", "Today's weather starts with reliable observations"], "home.latest_copy": ["正在读取探空、天气图和数据采集器状态。", "Reading soundings, weather maps and collector status."],
    "home.forecast_cache": ["ECMWF 预报缓存", "ECMWF forecast cache"], "home.sounding_source": ["探空主源 / 回退", "Sounding primary / fallback"], "home.analysis_link": ["打开中国天气分析 →", "Open China analysis →"],
    "home.ensemble_label": ["全球集合信号", "Global ensemble signal"], "home.native_steps": ["原生时间步", "Native steps"], "home.ensemble_title": ["不是一个答案，而是一组可能", "Not one answer, but a range of possibilities"], "home.ensemble_copy": ["AIFS ENS 和 WeatherNext 2 只在真实派生资料完成校验后展示。没有数据时，页面明确说明原因。", "AIFS ENS and WeatherNext 2 appear only after validated derived data is available. When data is missing, the reason is shown."], "home.ensemble_link": ["进入集合工作台 →", "Open ensemble workspace →"],
    "home.cyclone_label": ["热带系统", "Tropical systems"], "home.cyclone_title": ["看见路径分歧，也看见资料边界", "See track divergence, and the data boundary"], "home.cyclone_copy": ["WNC 1000 成员产品需要官方或合规 feed。当前页面不会用 WN2 或其他集合冒充 WNC。", "WNC 1000-member products require an official or compliant feed. This page never substitutes WN2 or another ensemble."], "home.cyclone_link": ["打开台风中心 →", "Open cyclone center →"],
    "home.tools_label": ["工作台", "Workspaces"], "home.open_data": ["本地读取", "Local read"], "home.obs_link": ["气象站实况", "Station observations"], "home.obs_desc": ["24 小时与历史窗口", "24-hour and historical windows"], "home.era5_link": ["ERA5 再分析", "ERA5 reanalysis"], "home.era5_desc": ["按需框选区域", "Draw a region on demand"], "home.colorbar_link": ["色条翻译器", "Colorbar translator"], "home.colorbar_desc": ["图片默认不上传", "Images stay local by default"], "home.about_link": ["关于与资料说明", "About and sources"], "home.disclaimer": ["自动诊断不等同于官方预报、预警或人工天气分析。", "Automatic diagnostics are not official forecasts, warnings or human analysis."]
  };
  function language() { return localStorage.getItem("cloudylake-language") || "zh"; }
  function applyLanguage() {
    const lang = language();
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    document.querySelectorAll("[data-i18n]").forEach((element) => { const pair = dictionary[element.dataset.i18n]; if (pair) element.textContent = pair[lang === "en" ? 1 : 0]; });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => { const pair = dictionary[element.dataset.i18nPlaceholder]; if (pair) element.placeholder = pair[lang === "en" ? 1 : 0]; });
    document.querySelectorAll("[data-lang-toggle]").forEach((element) => { element.textContent = lang === "en" ? "EN / 中" : "中 / EN"; });
    document.dispatchEvent(new CustomEvent("cloudylake:language", { detail: lang }));
  }
  function installLanguageToggle() {
    if (!document.querySelector("[data-lang-toggle]")) {
      const header = document.querySelector(".site-header, header");
      if (header) { const button = document.createElement("button"); button.className = "lang-toggle lang-toggle--injected"; button.type = "button"; button.dataset.langToggle = ""; button.setAttribute("aria-label", "切换语言"); (header.querySelector(".brand-row") || header).append(button); }
    }
    document.querySelectorAll("[data-lang-toggle]").forEach((element) => element.addEventListener("click", () => { localStorage.setItem("cloudylake-language", language() === "en" ? "zh" : "en"); applyLanguage(); }));
  }
  async function applySiteConfiguration() {
    try { const response = await fetch("/api/v1/site/config", { cache: "no-store" }); if (!response.ok) return; const site = await response.json(); const root = document.documentElement; for (const [key, value] of Object.entries(site.theme || {})) root.style.setProperty(`--site-${key}`, value); document.querySelectorAll(".site-footer").forEach((footer) => { const text = footer.querySelector("span:first-child"); if (text && site.footer?.copyright) text.textContent = site.footer.copyright; }); } catch (_) {}
  }
  async function applyServerSummary() {
    const target = document.querySelector(".header-motto"); if (!target) return;
    try { const response = await fetch("/api/v1/site/stats", { cache: "no-store" }); if (!response.ok) return; const stats = await response.json(); const raw = stats.congestion?.data_status || stats.data_health?.status || "unknown"; const status = ({ fresh: "新鲜", degraded: "降级", stale: "过期", unknown: "未知" }[raw] || "未知"); target.textContent = `资料：${status} · ${stats.monthly_page_views || 0} 次访问`; } catch (_) {}
  }
  document.addEventListener("DOMContentLoaded", () => { installLanguageToggle(); applyLanguage(); applySiteConfiguration(); applyServerSummary(); window.setInterval(applyServerSummary, 60000); window.addEventListener("scroll", () => document.documentElement.classList.toggle("has-scrolled", window.scrollY > 12), { passive: true }); });
})();
