function siteBytes(value) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = Number(value || 0);
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount.toFixed(index >= 3 ? 1 : 0)} ${units[index]}`;
}

async function applySiteConfiguration() {
  try {
    const response = await fetch("/api/v1/site/config", { cache: "no-store" });
    if (!response.ok) return;
    const site = await response.json();
    const root = document.documentElement;
    root.style.setProperty("--site-primary", site.theme.primary);
    root.style.setProperty("--site-accent", site.theme.accent);
    root.style.setProperty("--site-blue", site.theme.blue);
    root.style.setProperty("--sand", site.theme.primary);
    root.style.setProperty("--sand-light", site.theme.primary);
    root.style.setProperty("--sand-solid", site.theme.primary);
    root.style.setProperty("--sand-active", site.theme.accent);
    root.style.setProperty("--blue", site.theme.blue);
    root.style.setProperty("--blue-deep", site.theme.blue);
    const title = document.querySelector("#map-title");
    if (title) title.textContent = site.homepage.title;
    const subtitle = document.querySelector("#homepage-subtitle");
    if (subtitle) subtitle.textContent = site.homepage.subtitle;
    const notice = document.querySelector("#homepage-notice");
    if (notice) notice.textContent = site.homepage.notice;
    document.querySelectorAll(".main-nav__status small").forEach((element) => {
      element.textContent = site.version;
    });
  } catch {}
}

async function applyTrafficSummary() {
  const target = document.querySelector(".header-motto");
  if (!target) return;
  try {
    const response = await fetch("/api/v1/site/stats", { cache: "no-store" });
    if (!response.ok) return;
    const stats = await response.json();
    target.replaceChildren();
    const total = document.createElement("strong");
    total.textContent =
      `累计访问 ${Number(stats.requests || 0).toLocaleString("zh-CN")}`;
    const traffic = document.createElement("span");
    traffic.textContent = `响应流量 ${siteBytes(stats.response_bytes)}`;
    target.append(total, traffic);
    target.title = "站内统计自 V2.1.1 启用后累计，不等同于云服务商计费流量。";
  } catch {}
}

applySiteConfiguration();
applyTrafficSummary();
