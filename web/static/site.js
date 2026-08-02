async function applySiteConfiguration() {
  try {
    const response = await fetch("/api/v1/site/config", { cache: "no-store" });
    if (!response.ok) return;
    const site = await response.json();
    const root = document.documentElement;
    root.style.setProperty("--site-primary", site.theme.primary);
    root.style.setProperty("--site-accent", site.theme.accent);
    root.style.setProperty("--site-blue", site.theme.blue);
    root.style.setProperty("--teal", site.theme.primary);
    root.style.setProperty("--taupe", site.theme.primary);
    root.style.setProperty("--green", site.theme.primary);
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
    const stationTitle = document.querySelector("#sounding-title");
    if (stationTitle) stationTitle.textContent = site.homepage.station_title;
    const stationSubtitle = document.querySelector("#sounding-subtitle");
    if (stationSubtitle) {
      stationSubtitle.textContent = site.homepage.station_subtitle;
    }
    document.querySelectorAll(".site-footer").forEach((footer) => {
      const copyright = footer.querySelector("span:first-child");
      const contact = footer.querySelector('a[href^="mailto:"]');
      const powered = footer.querySelector("span:last-child");
      if (copyright) copyright.textContent = site.footer.copyright;
      if (contact) {
        contact.textContent = `Contact: ${site.footer.contact}`;
        contact.href = `mailto:${site.footer.contact}`;
      }
      if (powered) powered.textContent = site.footer.powered_with;
    });
    document.querySelectorAll(".main-nav__status small").forEach((element) => {
      element.textContent = site.version;
    });
  } catch {}
}

function renderCongestion(target, congestion) {
  const level = Math.min(3, Math.max(1, Number(congestion?.level || 1)));
  target.replaceChildren();
  const indicator = document.createElement("span");
  indicator.className = `server-congestion server-congestion--${level}`;
  indicator.setAttribute("aria-label", `服务器${congestion?.label || "状态未知"}`);
  const bars = document.createElement("span");
  bars.className = "server-congestion__bars";
  bars.setAttribute("aria-hidden", "true");
  bars.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
  const copy = document.createElement("span");
  copy.className = "server-congestion__copy";
  const title = document.createElement("strong");
  title.textContent = `服务器${congestion?.label || "状态未知"}`;
  const detail = document.createElement("small");
  detail.textContent = `${level} / 3`;
  copy.append(title, detail);
  indicator.append(bars, copy);
  target.append(indicator);
  const load = Number(congestion?.load_ratio);
  const memory = Number(congestion?.memory_used_percent);
  const disk = Number(congestion?.disk_used_percent);
  target.title = [
    "三格为通畅，两格为较忙，一格为拥挤。",
    Number.isFinite(load) ? `归一化负载 ${load.toFixed(2)}` : "",
    Number.isFinite(memory) ? `内存 ${memory.toFixed(1)}%` : "",
    Number.isFinite(disk) ? `磁盘 ${disk.toFixed(1)}%` : "",
  ].filter(Boolean).join(" · ");
}

async function applyServerSummary() {
  const target = document.querySelector(".header-motto");
  if (!target) return;
  try {
    const response = await fetch("/api/v1/site/stats", { cache: "no-store" });
    if (!response.ok) return;
    const stats = await response.json();
    renderCongestion(target, stats.congestion);
  } catch {}
}

applySiteConfiguration();
applyServerSummary();
window.setInterval(applyServerSummary, 60_000);

const navigationMenus = [...document.querySelectorAll(".nav-menu")];
navigationMenus.forEach((menu) => {
  menu.addEventListener("toggle", () => {
    if (!menu.open) return;
    navigationMenus.forEach((other) => {
      if (other !== menu) other.open = false;
    });
  });
});

document.addEventListener("pointerdown", (event) => {
  if (event.target.closest(".nav-menu")) return;
  navigationMenus.forEach((menu) => { menu.open = false; });
});
