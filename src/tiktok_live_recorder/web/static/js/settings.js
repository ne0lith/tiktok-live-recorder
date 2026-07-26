import { api, showToast } from "./api.js";
import { closeModal, isModalOpen, openModal, registerModalCloseHandler } from "./modal.js";
import { refreshStatus } from "./status.js";

const settingsModalId = "settings-modal";
const settingsToggle = document.getElementById("settings-toggle");

export async function loadSettings() {
  const [cookies, telegram, runtime] = await Promise.all([
    api("/api/settings/cookies"),
    api("/api/settings/telegram"),
    api("/api/settings/runtime"),
  ]);
  const cookiesEditor = document.getElementById("cookies-editor");
  const telegramEditor = document.getElementById("telegram-editor");
  const intervalInput = document.getElementById("interval-input");
  const telegramEnabled = document.getElementById("telegram-enabled");
  if (cookiesEditor) {
    cookiesEditor.value = JSON.stringify(cookies.cookies || {}, null, 2);
  }
  if (telegramEditor) {
    telegramEditor.value = JSON.stringify(telegram.telegram || {}, null, 2);
  }
  if (intervalInput) {
    intervalInput.value = String(runtime.automatic_interval_minutes ?? 5);
  }
  if (telegramEnabled) {
    telegramEnabled.checked = Boolean(runtime.use_telegram);
  }
}

export function syncRuntimeControls(status) {
  const intervalInput = document.getElementById("interval-input");
  const telegramEnabled = document.getElementById("telegram-enabled");
  if (intervalInput && document.activeElement !== intervalInput) {
    intervalInput.value = String(status.automatic_interval_minutes ?? 5);
  }
  if (telegramEnabled && document.activeElement !== telegramEnabled) {
    telegramEnabled.checked = Boolean(status.use_telegram);
  }
}

export function renderTelegramUploads(uploads) {
  const container = document.getElementById("telegram-uploads");
  const list = document.getElementById("telegram-uploads-list");
  if (!container || !list) return;
  if (!uploads.length) {
    container.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  container.classList.remove("hidden");
  list.innerHTML = uploads
    .slice(0, 8)
    .map(
      (entry) =>
        `<li><span class="upload-status ${entry.status}">${entry.status}</span> @${entry.username} · ${entry.file} · ${entry.message}</li>`,
    )
    .join("");
}

export function closeSettingsPanel() {
  closeModal(settingsModalId);
  settingsToggle?.classList.remove("is-active");
}

export async function openSettingsPanel() {
  closeModal("logs-modal");
  document.getElementById("logs-toggle")?.classList.remove("is-active");
  openModal(settingsModalId);
  settingsToggle?.classList.add("is-active");
  try {
    await loadSettings();
  } catch (error) {
    showToast(error.message);
  }
}

export function initSettingsInteractions() {
  registerModalCloseHandler(settingsModalId, () => {
    settingsToggle?.classList.remove("is-active");
  });

  settingsToggle?.addEventListener("click", async () => {
    if (isModalOpen(settingsModalId)) {
      closeSettingsPanel();
      return;
    }
    await openSettingsPanel();
  });

  document.getElementById("settings-close")?.addEventListener("click", closeSettingsPanel);

  document.getElementById("save-runtime-btn")?.addEventListener("click", async () => {
    try {
      const automatic_interval_minutes = Number.parseInt(
        document.getElementById("interval-input").value,
        10,
      );
      const use_telegram = document.getElementById("telegram-enabled").checked;
      await api("/api/settings/runtime", {
        method: "PUT",
        body: JSON.stringify({ automatic_interval_minutes, use_telegram }),
      });
      showToast("Runtime settings saved");
      await refreshStatus();
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("record-now-btn")?.addEventListener("click", async () => {
    const username = document.getElementById("record-username-input").value.trim();
    const roomId = document.getElementById("record-room-input").value.trim();
    if (!username && !roomId) {
      showToast("Enter a username or room ID");
      return;
    }
    try {
      const result = await api("/api/record", {
        method: "POST",
        body: JSON.stringify({
          username: username || undefined,
          room_id: roomId || undefined,
        }),
      });
      showToast(`Recording @${result.username}`);
      await refreshStatus();
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("save-cookies-btn")?.addEventListener("click", async () => {
    try {
      const cookies = JSON.parse(document.getElementById("cookies-editor").value);
      await api("/api/settings/cookies", {
        method: "PUT",
        body: JSON.stringify({ cookies }),
      });
      showToast("Cookies saved");
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("save-telegram-btn")?.addEventListener("click", async () => {
    try {
      const telegram = JSON.parse(document.getElementById("telegram-editor").value);
      await api("/api/settings/telegram", {
        method: "PUT",
        body: JSON.stringify({ telegram }),
      });
      showToast("Telegram settings saved");
    } catch (error) {
      showToast(error.message);
    }
  });
}
