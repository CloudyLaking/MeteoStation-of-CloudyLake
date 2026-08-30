(async function () {
  const target = document.querySelector("#ensemble-status");
  const statusText = (status) => ({ available: "可用", not_configured: "未配置", invalid: "快照无效" }[status] || "状态未知");
  try {
    const response = await fetch("/api/v1/ensemble/status", { cache: "no-store" });
    const data = await response.json();
    target.replaceChildren(...Object.values(data.products || {}).map((product) => {
      const article = document.createElement("article");
      article.className = "luna-status-panel";
      const detail = product.detail || `${product.members ?? "—"} 个成员 · ${product.native_steps?.length || 0} 个原生时间步`;
      article.innerHTML = `<div class="panel-rule"><span>${product.label}</span><b>${statusText(product.status)}</b></div><h2>${product.provider}</h2><p>${detail}</p><a href="${product.source_url}" target="_blank" rel="noopener">官方资料 →</a>`;
      return article;
    }));
  } catch (error) { target.textContent = "模型目录暂时不可用"; }
})();
