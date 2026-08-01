const metrics = document.querySelector("#admin-metrics");
const collectorStatus = document.querySelector("#collector-status");
const storageStatus = document.querySelector("#storage-status");
const feedback = document.querySelector("#admin-feedback");
const form = document.querySelector("#site-config-form");
const adminGuestbook = document.querySelector("#admin-guestbook");

function bytes(value) {
  if (!Number.isFinite(Number(value))) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = Number(value);
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }
  return `${amount.toFixed(index >= 3 ? 1 : 0)} ${units[index]}`;
}

function age(seconds) {
  if (!Number.isFinite(Number(seconds))) return "尚无状态";
  if (seconds < 90) return `${seconds} 秒前`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} 分钟前`;
  return `${(seconds / 3600).toFixed(1)} 小时前`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fillSite(site) {
  document.querySelector("#theme-primary").value = site.theme.primary;
  document.querySelector("#theme-accent").value = site.theme.accent;
  document.querySelector("#theme-blue").value = site.theme.blue;
  document.querySelector("#homepage-title").value = site.homepage.title;
  document.querySelector("#homepage-subtitle").value = site.homepage.subtitle;
  document.querySelector("#homepage-notice").value = site.homepage.notice;
}

async function loadStatus() {
  feedback.textContent = "正在读取服务器状态…";
  const response = await fetch("/api/v1/admin/status", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`状态读取失败：HTTP ${response.status}`);
  }
  const data = await response.json();
  const metricCards = metrics.querySelectorAll("strong");
  metricCards[0].textContent =
    `${data.disk.used_percent}% · 剩余 ${bytes(data.disk.free_bytes)}`;
  metricCards[1].textContent =
    data.memory.available_bytes === null
      ? "当前平台不支持"
      : bytes(data.memory.available_bytes);
  metricCards[2].textContent =
    Number(data.traffic.requests || 0).toLocaleString("zh-CN");
  metricCards[3].textContent = bytes(data.traffic.response_bytes);

  const labels = {
    forecast_collector: "IFS / AIFS",
    global_sounding_collector: "全球三日探空",
    wis2_sounding_collector: "WIS2 实时探空",
    weather_map_collector: "中国天气图",
  };
  collectorStatus.innerHTML = Object.entries(data.collectors)
    .map(([key, item]) => `
      <div>
        <span class="status-dot ${item.available ? "is-ready" : "is-missing"}"></span>
        <strong>${escapeHtml(labels[key] || key)}</strong>
        <small>${item.available ? age(item.age_seconds) : "尚未运行"}</small>
      </div>
    `)
    .join("");

  const storageLabels = {
    ecmwf_forecast: "IFS / AIFS 预报",
    wyoming: "Wyoming 探空",
    wis2_soundings: "WIS2 探空",
    ecmwf: "天气图场",
  };
  storageStatus.innerHTML = Object.entries(data.data_usage_bytes)
    .map(([key, value]) => `
      <div><span>${escapeHtml(storageLabels[key] || key)}</span><strong>${bytes(value)}</strong></div>
    `)
    .join("");
  renderPendingGuestbook(data.guestbook?.pending || []);
  fillSite(data.site);
  feedback.textContent = `状态更新于 ${new Date(data.checked_at).toLocaleString("zh-CN")}`;
}

function renderPendingGuestbook(entries) {
  if (!entries.length) {
    adminGuestbook.innerHTML = '<p class="empty-state">目前没有待审核留言。</p>';
    return;
  }
  adminGuestbook.innerHTML = entries.map((entry) => `
    <article>
      <header><strong>${escapeHtml(entry.name)}</strong><time>${new Date(entry.created_at).toLocaleString("zh-CN")}</time></header>
      <p>${escapeHtml(entry.message)}</p>
      <div><button data-guestbook-approve="${entry.id}" type="button">公开</button><button data-guestbook-delete="${entry.id}" type="button">删除</button></div>
    </article>
  `).join("");
}

adminGuestbook.addEventListener("click", async (event) => {
  const approve = event.target.closest("[data-guestbook-approve]");
  const remove = event.target.closest("[data-guestbook-delete]");
  if (!approve && !remove) return;
  const id = approve?.dataset.guestbookApprove || remove.dataset.guestbookDelete;
  const response = await fetch(
    approve ? `/api/v1/admin/guestbook/${id}/approve` : `/api/v1/admin/guestbook/${id}`,
    { method: approve ? "POST" : "DELETE", headers: { "X-Admin-Action": "confirm" } },
  );
  feedback.textContent = response.ok ? "留言状态已更新。" : `留言处理失败：HTTP ${response.status}`;
  if (response.ok) loadStatus().catch(() => {});
});

document.querySelector("#admin-reload").addEventListener("click", () => {
  loadStatus().catch((error) => { feedback.textContent = error.message; });
});

document.querySelectorAll("[data-refresh]").forEach((button) => {
  button.addEventListener("click", async () => {
    button.disabled = true;
    feedback.textContent = `正在提交${button.textContent}任务…`;
    try {
      const response = await fetch(
        `/api/v1/admin/refresh/${button.dataset.refresh}`,
        {
          method: "POST",
          headers: { "X-Admin-Action": "confirm" },
        },
      );
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      feedback.textContent = payload.detail;
      window.setTimeout(() => loadStatus().catch(() => {}), 2000);
    } catch (error) {
      feedback.textContent = `更新未启动：${error.message}`;
    } finally {
      button.disabled = false;
    }
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    version: "V2.1.1",
    theme: {
      primary: document.querySelector("#theme-primary").value,
      accent: document.querySelector("#theme-accent").value,
      blue: document.querySelector("#theme-blue").value,
    },
    homepage: {
      title: document.querySelector("#homepage-title").value.trim(),
      subtitle: document.querySelector("#homepage-subtitle").value.trim(),
      notice: document.querySelector("#homepage-notice").value.trim(),
    },
  };
  feedback.textContent = "正在保存主页设置…";
  const response = await fetch("/api/v1/admin/site", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Action": "confirm",
    },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  feedback.textContent = response.ok
    ? "设置已发布；访客刷新页面后即可看到。"
    : `保存失败：${result.detail || response.status}`;
});

loadStatus().catch((error) => { feedback.textContent = error.message; });
