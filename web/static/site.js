/* Shared shell: language preference, status strip, navigation and scroll state. */
(function () {
  const dictionary = {
    "nav.home": ["首页", "Home"], "nav.live": ["实况", "Live"], "nav.forecast": ["预报", "Forecast"],
    "nav.sounding": ["探空", "Soundings"], "nav.cyclones": ["台风", "Cyclones"], "nav.history": ["历史相似", "Analogs"], "nav.tools": ["工具", "Tools"],
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
    ,"ensemble.title": ["全球集合预报工作台", "Global Ensemble Forecast Workspace"]
    ,"ensemble.lede": ["按任意经纬度读取真实集合成员。细线表示单个成员，深色线为中位数，色带表示 25—75% 与 10—90% 范围。", "Read real ensemble members at any coordinate. Thin lines are members, the dark line is the median, and bands show the 25–75% and 10–90% ranges."]
    ,"cyclone.title": ["全球热带系统中心", "Global Tropical Cyclone Center"]
    ,"cyclone.lede": ["在同一画面区分官方实况、官方警报参考、WNC 生成候选与路径情景。任何来源都不会被冒充为另一种产品。", "Separate official observations, warning references, WNC candidates and track scenarios in one view. Sources are never relabelled as another product."]
  };
  function language() { return localStorage.getItem("cloudylake-language") || "zh"; }
  Object.assign(dictionary, {
    "nav.analysis": ["天气分析", "Weather analysis"],
    "nav.ensemble": ["集合预报", "Ensembles"],
    "nav.point": ["单点预报", "Point forecast"],
    "nav.sounding_forecast": ["探空预报", "Sounding forecast"],
    "nav.reanalysis": ["历史再分析", "Reanalysis"],
    "nav.colorbar": ["色条工具", "Colorbar tool"],
    "nav.about": ["关于", "About"],
  });
  const navItems = [
    ["nav.home", "/", ["/"]],
    ["nav.live", "/observations", ["/observations"]],
    ["nav.analysis", "/analysis", ["/analysis"]],
    ["nav.ensemble", "/ensemble", ["/ensemble"]],
    ["nav.point", "/forecast", ["/forecast"]],
    ["nav.sounding_forecast", "/sounding-forecast", ["/sounding-forecast"]],
    ["nav.cyclones", "/cyclones", ["/cyclones"]],
    ["nav.history", "/history/similar", ["/history"]],
    ["nav.reanalysis", "/reanalysis", ["/reanalysis"]],
    ["nav.colorbar", "/colorbar-translator", ["/colorbar-translator"]],
    ["nav.about", "/about", ["/about"]],
  ];

  function currentNavItem(paths) {
    const path = window.location.pathname.replace(/\/$/, "") || "/";
    return paths.some((candidate) => candidate === "/" ? path === "/" : path === candidate || path.startsWith(`${candidate}/`));
  }

  function navMarkup() {
    return navItems.map(([key, href, paths], index) => `${index ? '<i aria-hidden="true"></i>' : ''}<a href="${href}" data-i18n="${key}"${currentNavItem(paths) ? ' class="is-current" aria-current="page"' : ''}>${dictionary[key][0]}</a>`).join("");
  }

  function installUnifiedHeader() {
    if (window.location.pathname.startsWith("/admin")) return;
    document.body.classList.add("unified-page");
    const header = document.createElement("header");
    header.className = "floating-site-header";
    header.innerHTML = `<div class="floating-site-header__bar"><a class="home-brand" href="/" aria-label="云海观象台首页"><span class="home-brand__mark" aria-hidden="true">云海观象台</span><span class="floating-site-header__title"><strong>云海观象台</strong><small>CloudyLake's Observatory</small></span></a><nav class="floating-site-nav" aria-label="主导航">${navMarkup()}</nav><div class="floating-site-actions"><a class="header-data-status" href="/health/data">资料状态读取中</a><button class="lang-toggle" type="button" data-lang-toggle aria-label="切换语言">中 / EN</button></div></div>`;
    const legacy = document.querySelector("body > header");
    if (legacy) legacy.replaceWith(header);
    else document.body.prepend(header);
    const main = document.querySelector("body > main");
    if (main) main.classList.add("unified-main-shell");
    const firstPanel = ["main .map-panel", "main .station-query-form", "main .forecast-form", "main .reanalysis-form", "main .translator-source-panel", "main section"]
      .map((selector) => document.querySelector(selector)).find(Boolean);
    if (firstPanel) firstPanel.classList.add("signature-corner");
  }
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
    const targets = document.querySelectorAll(".header-motto, .header-data-status"); if (!targets.length) return;
    try { const response = await fetch("/api/v1/site/stats", { cache: "no-store" }); if (!response.ok) return; const stats = await response.json(); const raw = stats.congestion?.data_status || stats.data_health?.status || "unknown"; const status = ({ fresh: "资料新鲜", degraded: "资料降级", stale: "资料过期", unknown: "状态未知" }[raw] || "状态未知"); targets.forEach((target) => { target.textContent = `${status} · ${stats.monthly_page_views || 0} 次访问`; }); } catch (_) {}
  }

  function installAtmosphericGrid() {
    if (!document.body.matches(".home-page, .luna-page, .unified-page")) return;
    const canvas = document.createElement("canvas");
    canvas.className = "atmospheric-grid";
    canvas.setAttribute("aria-hidden", "true");
    document.body.prepend(canvas);
    const context = canvas.getContext("2d", { alpha: true });
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const coarse = window.matchMedia("(pointer: coarse)");
    const state = { width: 0, height: 0, dpr: 1, pointerX: -9999, pointerY: -9999, targetX: -9999, targetY: -9999, active: false, frame: 0, last: 0 };
    function resize() {
      state.width = window.innerWidth; state.height = window.innerHeight; state.dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.round(state.width * state.dpr); canvas.height = Math.round(state.height * state.dpr); canvas.style.width = `${state.width}px`; canvas.style.height = `${state.height}px`;
      context.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    }
    function displaced(x, y, time) {
      const dx = x - state.pointerX; const dy = y - state.pointerY; const distance = Math.hypot(dx, dy); const radius = coarse.matches ? 105 : 190;
      const influence = state.active && distance < radius ? Math.pow(1 - distance / radius, 2) : 0;
      const ambient = reduced.matches ? 0 : Math.sin(time * .00032 + x * .012 + y * .008) * 1.35;
      const push = influence * (coarse.matches ? 8 : 15);
      return { x: x + (distance ? dx / distance * push : 0) + ambient, y: y + (distance ? dy / distance * push : 0) + ambient * .45, influence };
    }
    function draw(timestamp) {
      if (!context) return;
      if (!reduced.matches && timestamp - state.last < 32) { state.frame = requestAnimationFrame(draw); return; }
      state.last = timestamp;
      if (state.active) { state.pointerX += (state.targetX - state.pointerX) * .12; state.pointerY += (state.targetY - state.pointerY) * .12; }
      context.clearRect(0, 0, state.width, state.height);
      const gap = state.width < 700 ? 42 : 36; const step = 18; const scrollPhase = reduced.matches ? 0 : (window.scrollY % gap) * .12;
      context.lineWidth = 1;
      const drawPath = (vertical, fixed) => {
        context.beginPath(); let peak = 0;
        const max = vertical ? state.height : state.width;
        for (let value = -step; value <= max + step; value += step) {
          const point = displaced(vertical ? fixed : value, vertical ? value : fixed + scrollPhase, timestamp); peak = Math.max(peak, point.influence);
          if (value === -step) context.moveTo(point.x, point.y); else context.lineTo(point.x, point.y);
        }
        context.strokeStyle = peak > .04 ? `rgba(125,104,152,${.07 + peak * .16})` : "rgba(18,110,104,.065)"; context.stroke();
      };
      for (let x = -gap; x < state.width + gap; x += gap) drawPath(true, x);
      for (let y = -gap; y < state.height + gap; y += gap) drawPath(false, y);
      if (state.active) {
        const glow = context.createRadialGradient(state.pointerX, state.pointerY, 0, state.pointerX, state.pointerY, coarse.matches ? 90 : 170);
        glow.addColorStop(0, "rgba(200,121,93,.11)"); glow.addColorStop(.52, "rgba(155,81,74,.045)"); glow.addColorStop(1, "rgba(255,255,255,0)");
        context.fillStyle = glow; context.fillRect(0, 0, state.width, state.height);
      }
      if (!reduced.matches) state.frame = requestAnimationFrame(draw);
    }
    function point(event) { const source = event.touches?.[0] || event; state.targetX = source.clientX; state.targetY = source.clientY; if (!state.active) { state.pointerX = state.targetX; state.pointerY = state.targetY; } state.active = true; if (reduced.matches) draw(performance.now()); }
    window.addEventListener("resize", () => { resize(); draw(performance.now()); }, { passive: true });
    window.addEventListener("pointermove", point, { passive: true });
    window.addEventListener("touchmove", point, { passive: true });
    document.addEventListener("pointerleave", () => { state.active = false; if (reduced.matches) draw(performance.now()); });
    reduced.addEventListener?.("change", () => { cancelAnimationFrame(state.frame); draw(performance.now()); });
    resize(); draw(performance.now());
  }
  document.addEventListener("DOMContentLoaded", () => { installUnifiedHeader(); installLanguageToggle(); applyLanguage(); applySiteConfiguration(); applyServerSummary(); installAtmosphericGrid(); window.setInterval(applyServerSummary, 60000); window.addEventListener("scroll", () => document.documentElement.classList.toggle("has-scrolled", window.scrollY > 12), { passive: true }); });
})();
