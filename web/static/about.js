const guestbookForm = document.querySelector("#guestbook-form");
const guestbookStatus = document.querySelector("#guestbook-status");

guestbookForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  guestbookStatus.textContent = "正在投递…";
  try {
    const response = await fetch("/api/v1/mailbox", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: document.querySelector("#guestbook-name").value.trim(),
        message: document.querySelector("#guestbook-message").value.trim(),
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      guestbookStatus.textContent = `投递失败：${payload.detail || response.status}`;
      return;
    }
    guestbookStatus.textContent = payload.detail;
    guestbookForm.reset();
  } catch (error) {
    guestbookStatus.textContent = "投递失败，请稍后再试。";
  }
});
