const guestbookForm = document.querySelector("#guestbook-form");
const guestbookList = document.querySelector("#guestbook-list");
const guestbookStatus = document.querySelector("#guestbook-status");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

async function loadGuestbook() {
  const response = await fetch("/api/v1/guestbook", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json();
  if (!payload.entries.length) {
    guestbookList.innerHTML = '<p class="empty-state">还没有公开留言，欢迎留下第一条。</p>';
    return;
  }
  guestbookList.innerHTML = payload.entries.map((entry) => `
    <article><header><strong>${escapeHtml(entry.name)}</strong><time>${new Date(entry.created_at).toLocaleDateString("zh-CN")}</time></header><p>${escapeHtml(entry.message)}</p></article>
  `).join("");
}

guestbookForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  guestbookStatus.textContent = "正在提交…";
  const response = await fetch("/api/v1/guestbook", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: document.querySelector("#guestbook-name").value.trim(),
      message: document.querySelector("#guestbook-message").value.trim(),
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    guestbookStatus.textContent = `提交失败：${payload.detail || response.status}`;
    return;
  }
  guestbookStatus.textContent = payload.detail;
  guestbookForm.reset();
});

loadGuestbook().catch(() => {
  guestbookList.innerHTML = '<p class="empty-state">留言暂时无法读取，请稍后再试。</p>';
});
