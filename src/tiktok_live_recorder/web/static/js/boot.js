import { api, bindToast, showToast } from "./api.js";
import { initConnectionBanner } from "./connection.js";
import { normalizeUsername } from "./format.js";
import { initKeyboardShortcuts } from "./keyboard.js";
import { initLogsInteractions } from "./logs.js";
import {
  initMediaInteractions,
  loadLibraryPreferences,
  refreshMedia,
} from "./media.js";
import { initModals } from "./modal.js";
import { initSegmentedControls } from "./segmented.js";
import { initSettingsInteractions, loadSettings } from "./settings.js";
import { syncStartupFfmpegFromDom } from "./runtime-ui.js";
import {
  connectEventStream,
  startMediaFallback,
} from "./sse.js";
import {
  initStatusInteractions,
  readProfileFromHash,
  refreshStatus,
  renderStatus,
  scrollToFocusedUser,
  setSelectedProfile,
} from "./status.js";
import {
  latestMedia,
  selectedProfile,
} from "./state.js";

async function boot() {
  syncStartupFfmpegFromDom();
  readProfileFromHash();
  loadLibraryPreferences();

  const [statusResult, mediaResult] = await Promise.allSettled([
    refreshStatus(),
    refreshMedia(),
  ]);

  if (statusResult.status === "rejected") {
    const message =
      statusResult.reason instanceof Error
        ? statusResult.reason.message
        : String(statusResult.reason);
    showToast(`Live status: ${message}`);
  }
  if (mediaResult.status === "rejected") {
    const message =
      mediaResult.reason instanceof Error
        ? mediaResult.reason.message
        : String(mediaResult.reason);
    showToast(`Media library: ${message}`);
  }

  loadSettings().catch((error) => {
    console.warn("Settings preload failed", error);
  });

  connectEventStream();
  startMediaFallback(refreshMedia);
}

bindToast(document.getElementById("toast"));
initConnectionBanner();
initModals();
initSegmentedControls();
initStatusInteractions();
initMediaInteractions();
initLogsInteractions();
initSettingsInteractions();
initKeyboardShortcuts();

window.addEventListener("ttlr:retry-connection", async () => {
  try {
    await refreshStatus();
    await refreshMedia({ force: true });
    connectEventStream();
  } catch (error) {
    showToast(error instanceof Error ? error.message : String(error));
  }
});

document.getElementById("add-user-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("add-user-input");
  const username = input?.value.trim();
  if (!username) return;
  try {
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({ username }),
    });
    if (input) input.value = "";
    showToast(`Added @${username.replace(/^@/, "")}`);
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("force-poll-btn")?.addEventListener("click", async () => {
  const btn = document.getElementById("force-poll-btn");
  if (btn?.disabled) return;
  try {
    btn?.classList.add("is-loading");
    await api("/api/poll", { method: "POST" });
    showToast("Poll requested");
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  } finally {
    btn?.classList.remove("is-loading");
  }
});

window.addEventListener("hashchange", () => {
  const match = window.location.hash.match(/^#user\/(.+)$/);
  const username = match ? normalizeUsername(decodeURIComponent(match[1])) : null;
  if ((username || null) === (selectedProfile || null)) return;
  setSelectedProfile(username);
});

boot();
