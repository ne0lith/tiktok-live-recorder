import { api } from "./api.js";
import { renderActivityFeed } from "./activity.js";
import {
  formatBytes,
  formatDuration,
  formatNextPoll,
  formatTimestamp,
  normalizeUsername,
  usernamesMatch,
} from "./format.js";
import {
  STATE_SORT_ORDER,
  latestMedia,
  latestStatus,
  selectedProfile,
  setLatestStatus,
  setSelectedProfileValue,
  setStatusFilter,
  statusFilter,
} from "./state.js";
import { refreshPendingConvertCount, renderMedia, syncConvertJobUi } from "./media.js";
import { renderTelegramUploads, syncRuntimeControls } from "./runtime-ui.js";

const statusBoard = document.getElementById("status-board");
const statusMeta = document.getElementById("status-meta");
const pollSummary = document.getElementById("poll-summary");
const summaryChips = document.getElementById("summary-chips");
const addUserForm = document.getElementById("add-user-form");
const forcePollBtn = document.getElementById("force-poll-btn");

const ACTIVE_STATES = new Set([
  "live",
  "starting",
  "recording",
  "converting",
  "stopping",
  "error",
]);

export function deriveRows(status) {
  const paused = new Set((status.paused || []).map((u) => u.toLowerCase()));
  const recordings = new Map(
    (status.recordings || []).map((entry) => [entry.username, entry]),
  );
  const poll = status.poll || {};
  const rows = new Map();

  const ensure = (username, state) => {
    const key = username.toLowerCase();
    if (!rows.has(key)) {
      rows.set(key, {
        username,
        state,
        room_id: null,
        elapsed_seconds: null,
        bytes_written: null,
        output_path: null,
        convert_progress: null,
      });
    }
    return rows.get(key);
  };

  (status.users || []).forEach((username) => {
    const row = ensure(username, paused.has(username.toLowerCase()) ? "paused" : "offline");
    if (paused.has(username.toLowerCase())) row.state = "paused";
  });

  (poll.recording || []).forEach((username) => {
    ensure(username, "recording").state = "recording";
  });
  (poll.offline || []).forEach((username) => {
    const row = ensure(username, "offline");
    if (!paused.has(username.toLowerCase())) row.state = "offline";
  });
  (poll.paused || []).forEach((username) => {
    ensure(username, "paused").state = "paused";
  });
  (poll.errors || []).forEach((entry) => {
    const username = String(entry).split(" ")[0];
    ensure(username, "error").state = "error";
  });
  (poll.starting || []).forEach((entry) => {
    const row = ensure(entry.username, "live");
    row.state = "live";
    row.room_id = entry.room_id;
  });

  recordings.forEach((entry, username) => {
    if (entry.is_alive === false) return;
    const row = ensure(username, entry.status || "recording");
    row.state = entry.status || row.state;
    row.room_id = entry.room_id || row.room_id;
    row.elapsed_seconds = entry.elapsed_seconds;
    row.bytes_written = entry.bytes_written;
    row.output_path = entry.output_path || row.output_path;
    row.convert_progress = entry.convert_progress || null;
  });

  return Array.from(rows.values()).sort((a, b) => {
    const orderA = STATE_SORT_ORDER[a.state] ?? 99;
    const orderB = STATE_SORT_ORDER[b.state] ?? 99;
    if (orderA !== orderB) return orderA - orderB;
    return a.username.localeCompare(b.username);
  });
}

function countByState(rows) {
  const counts = { live: 0, recording: 0, offline: 0, paused: 0, error: 0 };
  for (const row of rows) {
    if (row.state === "live" || row.state === "starting") counts.live += 1;
    else if (row.state === "recording" || row.state === "converting" || row.state === "stopping") {
      counts.recording += 1;
    } else if (row.state === "paused") counts.paused += 1;
    else if (row.state === "error") counts.error += 1;
    else counts.offline += 1;
  }
  return counts;
}

function rowMatchesFilter(row) {
  if (statusFilter === "all") return true;
  if (statusFilter === "live") return row.state === "live" || row.state === "starting";
  if (statusFilter === "recording") {
    return row.state === "recording" || row.state === "converting" || row.state === "stopping";
  }
  if (statusFilter === "offline") return row.state === "offline";
  if (statusFilter === "paused") return row.state === "paused";
  if (statusFilter === "error") return row.state === "error";
  return true;
}

function emptyUsersMessage(status) {
  if (statusFilter !== "all") {
    const label = statusFilter.charAt(0).toUpperCase() + statusFilter.slice(1);
    return `No users match "${label}".`;
  }
  if (status.mode === "followers") return "No followers loaded yet.";
  if (status.mode === "automatic") return "No tracked user yet.";
  return "No users in watchlist yet.";
}

function applyModeUI(status) {
  const mode = status?.mode || "watchlist";
  document.body.dataset.mode = mode;
  addUserForm?.classList.toggle("hidden", mode !== "watchlist");
}

function syncPollUI(status) {
  const polling = Boolean(status?.poll_in_progress);
  forcePollBtn?.classList.toggle("is-loading", polling);
  if (forcePollBtn) forcePollBtn.disabled = polling;
  document.body.classList.toggle("poll-in-progress", polling);
}

function renderPollSummary(status) {
  const poll = status.poll || {};
  const groups = [
    ["Finished", poll.finished],
    ["Skipped", poll.skipped],
    ["Errors", poll.errors],
  ].filter(([, items]) => items && items.length);

  if (!groups.length && !status.poll_label) {
    pollSummary.classList.add("hidden");
    pollSummary.innerHTML = "";
    return;
  }

  const label = status.poll_label ? `<span class="poll-label">${status.poll_label}</span>` : "";
  const chunks = groups
    .map(([name, items]) => {
      const values = items
        .map((entry) => {
          const text = String(entry);
          return text.startsWith("@") ? text : `@${text}`;
        })
        .join(", ");
      return `<div class="poll-group"><span class="poll-group-label">${name}</span> ${values}</div>`;
    })
    .join("");

  pollSummary.classList.remove("hidden");
  pollSummary.innerHTML = `${label}${chunks}`;
}

export function renderSummaryChips(status) {
  if (!summaryChips) return;
  const rows = deriveRows(status);
  const counts = countByState(rows);
  const version = document.body.dataset.version || "";
  const chips = [
    { filter: "all", label: "All" },
    { filter: "live", label: `Live ${counts.live}` },
    { filter: "recording", label: `Recording ${counts.recording}` },
    { filter: "offline", label: `Offline ${counts.offline}` },
    { filter: "paused", label: `Paused ${counts.paused}` },
    { filter: "error", label: `Errors ${counts.error}` },
  ];

  const metaChips = [];
  if (status.poll_in_progress) {
    metaChips.push(`<span class="summary-chip summary-chip--meta summary-chip--polling">Poll running…</span>`);
  }
  metaChips.push(`<span class="summary-chip summary-chip--meta">Last poll ${formatTimestamp(status.last_poll_at)}</span>`);
  metaChips.push(`<span class="summary-chip summary-chip--meta">Next ${formatNextPoll(status)}</span>`);
  if (version) metaChips.push(`<span class="summary-chip summary-chip--meta">v${version}</span>`);
  if (status.ffmpeg?.path) {
    const sourceShort =
      status.ffmpeg.source === "vendor"
        ? "FFmpeg vendor"
        : status.ffmpeg.source === "system"
          ? "FFmpeg system"
          : "FFmpeg custom";
    const hevcShort = status.ffmpeg.hevc_capable ? "HEVC OK" : "HEVC !";
    const title = `${status.ffmpeg.path}\n${status.ffmpeg.version || ""}`;
    metaChips.push(
      `<span class="summary-chip summary-chip--meta summary-chip--ffmpeg" title="${title.replace(/"/g, "&quot;")}">${sourceShort} · ${hevcShort}</span>`,
    );
  }

  const focusChip = selectedProfile
    ? `<button type="button" class="summary-chip summary-chip--focus" data-clear-focus="1" title="Clear focus">@${selectedProfile} <span aria-hidden="true">x</span></button>`
    : "";

  const filterChips = chips
    .map(
      ({ filter, label }) =>
        `<button type="button" class="summary-chip summary-chip--filter${statusFilter === filter ? " is-active" : ""}" data-filter="${filter}">${label}</button>`,
    )
    .join("");

  summaryChips.innerHTML = `${filterChips}${focusChip}<div class="summary-chips-meta">${metaChips.join("")}</div>`;
}

export function setStatusFilterValue(filter) {
  setStatusFilter(filter);
  if (latestStatus) renderStatus(latestStatus);
}

function profileLinkMarkup(username, { active = false } = {}) {
  return `<button type="button" class="profile-link${active ? " is-active" : ""}" data-profile="${username}">@${username}</button>`;
}

function renderStatusActions(row, status) {
  const paused = (status.paused || [])
    .map((u) => u.toLowerCase())
    .includes(row.username.toLowerCase());
  const isWatchlist = status.mode === "watchlist";
  const canStop =
    row.state === "recording" ||
    row.state === "converting" ||
    row.state === "stopping";
  const buttons = [];

  if (canStop) {
    buttons.push(
      `<button class="btn btn-danger btn-small" data-action="stop" data-user="${row.username}">Stop</button>`,
    );
  }
  buttons.push(
    paused
      ? `<button class="btn btn-ghost btn-small" data-action="resume" data-user="${row.username}">Resume</button>`
      : `<button class="btn btn-ghost btn-small" data-action="pause" data-user="${row.username}">Pause</button>`,
  );
  if (isWatchlist) {
    buttons.push(
      `<button class="btn btn-ghost btn-small" data-action="remove" data-user="${row.username}">Remove</button>`,
    );
  }

  return `<div class="status-actions">${buttons.join("")}</div>`;
}

function formatStateLabel(row) {
  if (row.state === "converting") {
    const percent = row.convert_progress?.percent;
    if (percent != null) return `converting ${percent}%`;
  }
  return row.state;
}

function renderConvertProgress(row) {
  if (row.state !== "converting") return "";
  const percent = row.convert_progress?.percent;
  if (percent == null) return "";
  const safe = Math.max(0, Math.min(100, percent));
  const eta =
    row.convert_progress?.duration_seconds &&
    row.convert_progress?.out_time_seconds != null
      ? formatDuration(
          Math.max(
            0,
            row.convert_progress.duration_seconds -
              row.convert_progress.out_time_seconds,
          ),
        )
      : null;
  const etaLabel = eta && eta !== "0s" ? ` · ~${eta} left` : "";
  return `<div class="convert-progress" role="progressbar" aria-valuenow="${safe}" aria-valuemin="0" aria-valuemax="100" title="MP4 conversion in progress">
    <div class="convert-progress-track">
      <div class="convert-progress-fill" style="width: ${safe}%"></div>
    </div>
    <span class="convert-progress-meta">${safe}%${etaLabel}</span>
  </div>`;
}

function partitionStatusRows(rows) {
  const active = [];
  const idle = [];
  for (const row of rows) {
    if (ACTIVE_STATES.has(row.state)) active.push(row);
    else idle.push(row);
  }
  return { active, idle };
}

function renderStatusLine(row, status) {
  const focused = usernamesMatch(row.username, selectedProfile);
  const isActive = ACTIVE_STATES.has(row.state);
  const details = [];
  if (isActive) {
    if (row.room_id) details.push(`Room ${row.room_id}`);
    const elapsed = formatDuration(row.elapsed_seconds);
    if (elapsed && elapsed !== "-") details.push(elapsed);
    const size = formatBytes(row.bytes_written);
    if (size && size !== "-") details.push(size);
  }
  const detailMarkup = details.length
    ? `<p class="status-line-detail">${details.join(" · ")}</p>`
    : "";
  const progressMarkup =
    isActive && row.state === "converting" ? renderConvertProgress(row) : "";

  return `
    <div class="status-line${isActive ? " status-line--active" : ""}${focused ? " status-line--focused" : ""}" data-username="${row.username}">
      <div class="status-line-body">
        <div class="status-line-main">
          ${profileLinkMarkup(row.username, { active: focused })}
          <span class="badge ${row.state}">${formatStateLabel(row)}</span>
        </div>
        ${detailMarkup}
        ${progressMarkup}
      </div>
      <div class="status-line-actions">${renderStatusActions(row, status)}</div>
    </div>
  `;
}

function renderStatusBoard(rows, status) {
  if (!statusBoard) return;
  if (!rows.length) {
    statusBoard.innerHTML = `<p class="empty">${emptyUsersMessage(status)}</p>`;
    statusBoard.className = "status-list";
    return;
  }

  const { active, idle } = partitionStatusRows(rows);
  const parts = [];

  if (active.length) {
    parts.push('<p class="status-section-label">Active</p>');
    parts.push(...active.map((row) => renderStatusLine(row, status)));
  }
  if (idle.length) {
    if (active.length) {
      parts.push('<p class="status-section-label">Watchlist</p>');
    }
    parts.push(...idle.map((row) => renderStatusLine(row, status)));
  }

  statusBoard.className = "status-list";
  statusBoard.innerHTML = parts.join("");
}

export function scrollToFocusedUser() {
  if (!selectedProfile || !statusBoard) return;
  const item = statusBoard.querySelector(
    `[data-username="${CSS.escape(selectedProfile)}"]`,
  );
  item?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

export function setSelectedProfile(username) {
  setSelectedProfileValue(username ? normalizeUsername(username) : null);
  const base = `${window.location.pathname}${window.location.search}`;
  if (selectedProfile) {
    window.history.replaceState(null, "", `${base}#user/${encodeURIComponent(selectedProfile)}`);
  } else {
    window.history.replaceState(null, "", base);
  }
  if (latestStatus) renderStatus(latestStatus);
  else renderSummaryChips(latestStatus || {});
  if (Object.keys(latestMedia).length) {
    renderMedia(latestMedia);
  }
  if (selectedProfile) {
    requestAnimationFrame(() => scrollToFocusedUser());
  }
}

export function readProfileFromHash() {
  const match = window.location.hash.match(/^#user\/(.+)$/);
  if (match) {
    setSelectedProfileValue(normalizeUsername(decodeURIComponent(match[1])));
  }
}

export function renderStatus(status) {
  setLatestStatus(status);
  applyModeUI(status);
  syncPollUI(status);
  let rows = deriveRows(status);
  rows = rows.filter(rowMatchesFilter);

  const pollLabel = status.poll_label ? ` · ${status.poll_label}` : "";
  if (statusMeta) {
    statusMeta.textContent = `All users · ${status.mode}${pollLabel} · last poll ${formatTimestamp(
      status.last_poll_at,
    )} · interval ${status.automatic_interval_minutes} min`;
  }

  renderPollSummary(status);
  renderSummaryChips(status);
  renderActivityFeed(status.activity || []);
  renderTelegramUploads(status.telegram_uploads || []);
  syncRuntimeControls(status);
  if (status.convert_job?.running) {
    syncConvertJobUi(status.convert_job);
  }

  if (!rows.length) {
    if (statusBoard) {
      statusBoard.innerHTML = `<p class="empty">${emptyUsersMessage(status)}</p>`;
    }
    return;
  }

  renderStatusBoard(rows, status);
}

export async function refreshStatus() {
  const status = await api("/api/status");
  renderStatus(status);
}

export function initStatusInteractions() {
  summaryChips?.addEventListener("click", (event) => {
    const clearFocus = event.target.closest("[data-clear-focus]");
    if (clearFocus) {
      setSelectedProfile(null);
      return;
    }
    const chip = event.target.closest("[data-filter]");
    if (!chip) return;
    setStatusFilterValue(chip.dataset.filter);
  });

  statusBoard?.addEventListener("click", handleStatusAction);
}

async function handleStatusAction(event) {
  const profileButton = event.target.closest("button[data-profile]");
  if (profileButton) {
    setSelectedProfile(profileButton.dataset.profile);
    return;
  }

  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action, user } = button.dataset;
  const { showToast } = await import("./api.js");
  try {
    if (action === "stop") {
      await api(`/api/recordings/${encodeURIComponent(user)}/stop`, { method: "POST" });
      showToast(`Stopping @${user}`);
    } else if (action === "pause") {
      await api(`/api/users/${encodeURIComponent(user)}/pause`, { method: "POST" });
      showToast(`Paused @${user}`);
    } else if (action === "resume") {
      await api(`/api/users/${encodeURIComponent(user)}/resume`, { method: "POST" });
      showToast(`Resumed @${user}`);
    } else if (action === "remove") {
      if (!confirm(`Remove @${user} from the watchlist?`)) return;
      await api(`/api/users/${encodeURIComponent(user)}`, { method: "DELETE" });
      showToast(`Removed @${user}`);
    }
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
}

// noop kept for media.js import compatibility
export function updateProfileBanner() {}
