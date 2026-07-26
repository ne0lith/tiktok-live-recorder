import { api, showToast } from "./api.js";
import { formatBytes } from "./format.js";
import { closeModal, isModalOpen, openModal, registerModalCloseHandler } from "./modal.js";
import { LOG_REFRESH_MS, logState } from "./state.js";

const logsModalId = "logs-modal";
const logsToggle = document.getElementById("logs-toggle");
const logsMeta = document.getElementById("logs-meta");
const logOutput = document.getElementById("log-output");

function parseLogLineLevel(line) {
  const match = line.match(/ \[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\] /);
  return match ? match[1] : null;
}

function renderLogs(payload) {
  const lines = payload.lines || [];
  const truncatedNote = payload.truncated ? " · truncated" : "";
  if (logsMeta) {
    logsMeta.textContent = `${payload.path || "log file"} · ${lines.length} line${
      lines.length === 1 ? "" : "s"
    } · ${formatBytes(payload.size)}${truncatedNote}`;
  }

  const atBottom =
    logOutput &&
    logOutput.scrollHeight - logOutput.scrollTop - logOutput.clientHeight < 24;
  if (atBottom) logState.stickToBottom = true;

  logState.lastText = lines.join("\n");
  logOutput?.replaceChildren();
  if (!lines.length) {
    const empty = document.createElement("div");
    empty.className = "log-line empty";
    empty.textContent = "No log lines yet.";
    logOutput?.append(empty);
    return;
  }

  for (const line of lines) {
    const row = document.createElement("div");
    const level = parseLogLineLevel(line);
    row.className = `log-line${level ? ` level-${level}` : ""}`;
    row.textContent = line;
    logOutput?.append(row);
  }

  if (logState.stickToBottom && logOutput) {
    logOutput.scrollTop = logOutput.scrollHeight;
  }
}

export async function refreshLogs() {
  const lines = document.getElementById("logs-lines")?.value || "300";
  const level = document.getElementById("logs-level")?.value || "";
  const params = new URLSearchParams({ lines: String(lines) });
  if (level) params.set("level", level);
  const payload = await api(`/api/logs?${params.toString()}`);
  renderLogs(payload);
}

function stopLogRefresh() {
  if (logState.timer) {
    clearInterval(logState.timer);
    logState.timer = null;
  }
}

function startLogRefresh() {
  stopLogRefresh();
  if (!document.getElementById("logs-autorefresh")?.checked) return;
  logState.timer = setInterval(() => {
    refreshLogs().catch((error) => showToast(error.message));
  }, LOG_REFRESH_MS);
}

export function isLogsOpen() {
  return isModalOpen(logsModalId);
}

export function closeLogsPanel() {
  closeModal(logsModalId);
  logsToggle?.classList.remove("is-active");
  stopLogRefresh();
}

export async function openLogsPanel() {
  closeModal("settings-modal");
  document.getElementById("settings-toggle")?.classList.remove("is-active");
  openModal(logsModalId);
  logsToggle?.classList.add("is-active");
  logState.stickToBottom = true;
  try {
    await refreshLogs();
    startLogRefresh();
  } catch (error) {
    showToast(error.message);
  }
}

async function handleLogFilterChange() {
  if (!isLogsOpen()) return;
  try {
    logState.stickToBottom = true;
    await refreshLogs();
  } catch (error) {
    showToast(error.message);
  }
}

export function initLogsInteractions() {
  registerModalCloseHandler(logsModalId, () => {
    logsToggle?.classList.remove("is-active");
    stopLogRefresh();
  });

  logsToggle?.addEventListener("click", async () => {
    if (isLogsOpen()) {
      closeLogsPanel();
      return;
    }
    await openLogsPanel();
  });

  document.getElementById("logs-clear-btn")?.addEventListener("click", async () => {
    if (
      !confirm(
        "Clear the recorder log file? This truncates tiktok-recorder.log and deletes rotation backups. New log lines will continue from here.",
      )
    ) {
      return;
    }
    try {
      const payload = await api("/api/logs/clear", { method: "POST" });
      const removed = payload.removed_backups?.length || 0;
      const suffix = removed ? ` (${removed} backup${removed === 1 ? "" : "s"} removed)` : "";
      showToast(`Log cleared${suffix}`);
      logState.stickToBottom = true;
      await refreshLogs();
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("logs-refresh-btn")?.addEventListener("click", async () => {
    try {
      logState.stickToBottom = true;
      await refreshLogs();
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("logs-copy-btn")?.addEventListener("click", async () => {
    const text = logState.lastText || "";
    if (!text) {
      showToast("Nothing to copy");
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      showToast("Log copied to clipboard");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Could not copy log");
    }
  });

  document.getElementById("logs-lines")?.addEventListener("change", handleLogFilterChange);
  document.getElementById("logs-level")?.addEventListener("change", handleLogFilterChange);

  document.getElementById("logs-autorefresh")?.addEventListener("change", () => {
    if (!isLogsOpen()) return;
    if (document.getElementById("logs-autorefresh")?.checked) startLogRefresh();
    else stopLogRefresh();
  });

  logOutput?.addEventListener("scroll", () => {
    if (!logOutput) return;
    const atBottom =
      logOutput.scrollHeight - logOutput.scrollTop - logOutput.clientHeight < 24;
    logState.stickToBottom = atBottom;
  });
}
