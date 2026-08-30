(async function () {
  const target = document.querySelector("#cyclone-status");
  try {
    const response = await fetch("/api/v1/cyclones/status", { cache: "no-store" });
    const data = await response.json();
    const item = data.wnc || {};
    const article = document.createElement("article");
    article.className = "luna-status-panel luna-status-panel--violet";
    const status = ({ available: "可用", not_configured: "未配置", invalid: "快照无效" }[item.status] || "状态未知");
    const detail = item.status === "not_configured" ? "官方或合规的 WNC feed 尚未配置；本站不会用其他模型填充成员。" : (item.detail || "已配置派生快照");
    article.innerHTML = `<div class="panel-rule"><span>${item.label || "WeatherNext Cyclones"}</span><b>${status}</b></div><h2>${item.member_target || 1000} 成员目标</h2><p>${detail}</p><p class="muted">来源：Weather Lab · 最长 ${item.lead_time_hours || 360} h</p>`;
    target.replaceChildren(article);
  } catch (error) { target.textContent = "WNC 状态暂时不可用"; }
})();
