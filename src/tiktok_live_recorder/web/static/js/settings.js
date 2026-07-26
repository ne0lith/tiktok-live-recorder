import { api, showToast } from "./api.js";
import { closeModal, isModalOpen, openModal, registerModalCloseHandler } from "./modal.js";
import { syncFfmpegInfo, syncStartupFfmpegFromDom } from "./runtime-ui.js";
import { latestMedia, latestStatus } from "./state.js";
import { refreshStatus } from "./status.js";
import { renderMedia, saveShowLegacyPreference, syncLibraryShowLegacyToggle } from "./media.js";

const settingsModalId = "settings-modal";
const settingsToggle = document.getElementById("settings-toggle");

export async function loadFfmpegInfo() {
  try {
    const ffmpeg = await api("/api/ffmpeg");
    syncFfmpegInfo(ffmpeg);
    return ffmpeg;
  } catch (error) {
    console.warn("FFmpeg info fetch failed", error);
    if (latestStatus?.ffmpeg?.path) {
      syncFfmpegInfo(latestStatus.ffmpeg);
      return latestStatus.ffmpeg;
    }
    return null;
  }
}

export async function loadSettings() {
  const [cookiesResult, telegramResult, runtimeResult] = await Promise.allSettled([
    api("/api/settings/cookies"),
    api("/api/settings/telegram"),
    api("/api/settings/runtime"),
  ]);

  const cookiesEditor = document.getElementById("cookies-editor");
  const telegramEditor = document.getElementById("telegram-editor");
  const intervalInput = document.getElementById("interval-input");
  const telegramEnabled = document.getElementById("telegram-enabled");

  if (cookiesResult.status === "fulfilled" && cookiesEditor) {
    cookiesEditor.value = JSON.stringify(cookiesResult.value.cookies || {}, null, 2);
  }
  if (telegramResult.status === "fulfilled" && telegramEditor) {
    telegramEditor.value = JSON.stringify(telegramResult.value.telegram || {}, null, 2);
  }
  if (runtimeResult.status === "fulfilled") {
    const runtime = runtimeResult.value;
    if (intervalInput) {
      intervalInput.value = String(runtime.automatic_interval_minutes ?? 5);
    }
    if (telegramEnabled) {
      telegramEnabled.checked = Boolean(runtime.use_telegram);
    }
  }

  syncLibraryShowLegacyToggle();

  await loadFfmpegInfo();
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
  syncStartupFfmpegFromDom();
  try {
    await Promise.allSettled([loadSettings(), refreshStatus()]);
  } catch (error) {
    showToast(error.message);
  } finally {
    await loadFfmpegInfo();
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

  document.getElementById("library-show-legacy")?.addEventListener("change", (event) => {
    saveShowLegacyPreference(event.target.checked);
    renderMedia(latestMedia);
  });

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
