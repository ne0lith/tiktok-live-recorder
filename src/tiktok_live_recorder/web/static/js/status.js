import { api } from "./api.js";
import { renderActivityFeed, loadActivityPreferences } from "./activity.js";
import {
  formatBytes,
  formatDuration,
  formatNextPoll,
  formatTimestamp,
  hasRenamedHandle,
  normalizeUsername,
  tiktokProfileUrl,
  currentTikTokHandle,
  usernamesMatch,
} from "./format.js";
import {
  STATE_SORT_ORDER,
  STORAGE_HIDE_PAUSED_KEY,
  hidePausedUsers,
  latestMedia,
  latestStatus,
  selectedProfile,
  setHidePausedUsers,
  setLatestStatus,
  setSelectedProfileValue,
  setStatusFilter,
  statusFilter,
} from "./state.js";
import { renderMedia, sumLibraryBytesForUser } from "./media.js";
import { renderTelegramUploads, syncRuntimeControls } from "./runtime-ui.js";
import {
  buildUserActionButtons,
  profileLinkMarkup,
  runUserAction,
} from "./user-actions.js";

const statusBoard = document.getElementById("status-board");
const statusMeta = document.getElementById("status-meta");
const statusOps = document.getElementById("status-ops");
const summaryFilters = document.getElementById("summary-filters");
const summaryMeta = document.getElementById("summary-meta");
const addUserForm = document.getElementById("add-user-form");
const forcePollBtn = document.getElementById("force-poll-btn");

const ACTIVE_STATES = new Set([
  "live",
  "starting",
  "recording",
  "stopping",
  "error",
]);

const POLL_NAME_CAP = 6;

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
    else if (row.state === "recording" || row.state === "stopping") {
      counts.recording += 1;
    } else if (row.state === "paused") counts.paused += 1;
    else if (row.state === "error") counts.error += 1;
    else counts.offline += 1;
  }
  return counts;
}

function rowMatchesFilter(row) {
  if (statusFilter === "all") {
    if (hidePausedUsers && row.state === "paused") {
      return usernamesMatch(row.username, selectedProfile);
    }
    return true;
  }
  if (statusFilter === "live") return row.state === "live" || row.state === "starting";
  if (statusFilter === "recording") {
    return row.state === "recording" || row.state === "stopping";
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

function formatHandle(entry) {
  const text = String(entry);
  return text.startsWith("@") ? text : `@${text}`;
}

function formatNameList(items, cap = POLL_NAME_CAP) {
  const list = (items || []).map(formatHandle);
  if (!list.length) return "";
  if (list.length <= cap) return list.join(", ");
  const shown = list.slice(0, cap).join(", ");
  return `${shown} +${list.length - cap} more`;
}

function renderStatusOps(status) {
  if (!statusOps) return;
  const poll = status.poll || {};
  const queue = status.convert_queue || {};
  const jobs = status.media_jobs || [];
  const pending = queue.pending || 0;
  const active = queue.active || 0;
  const max = queue.max_concurrent || 1;
  const convertBusy = pending + active > 0 || jobs.length > 0;

  const recordingSet = new Set(
    (poll.recording || []).map((u) => String(u).toLowerCase()),
  );
  (status.recordings || []).forEach((entry) => {
    if (entry?.username) recordingSet.add(String(entry.username).toLowerCase());
  });
  // "Starting" only while not yet in an active recording (snapshot used to keep
  // newly found lives here for the whole interval after spawn).
  const starting = (poll.starting || [])
    .map((entry) => (typeof entry === "string" ? entry : entry.username || entry))
    .filter((username) => username && !recordingSet.has(String(username).toLowerCase()));
  const countPills = [
    ["Starting", starting],
    ["Recording", poll.recording],
    ["Offline", poll.offline],
    ["Paused", poll.paused],
    ["Finished", poll.finished],
    ["Skipped", poll.skipped],
    ["Errors", poll.errors],
  ]
    .filter(([, items]) => items && items.length)
    .map(
      ([label, items]) =>
        `<span class="status-ops-pill"><span class="status-ops-pill-label">${label}</span> ${items.length}</span>`,
    )
    .join("");

  // Only expand names for actionable / noisy-small groups - never dump offline lists.
  const detailGroups = [
    ["Starting", starting],
    ["Skipped", poll.skipped],
    ["Errors", poll.errors],
  ].filter(([, items]) => items && items.length);

  const detailHtml = detailGroups
    .map(
      ([label, items]) =>
        `<div class="status-ops-detail-row"><span class="status-ops-detail-label">${label}</span> ${formatNameList(items)}</div>`,
    )
    .join("");

  const hasPollBlock = Boolean(status.poll_label || countPills || detailHtml);
  const blocks = [];

  if (hasPollBlock) {
    const title = status.poll_label || "Last poll";
    const running = status.poll_in_progress
      ? `<span class="status-ops-badge">Running</span>`
      : "";
    blocks.push(`<div class="status-ops-block">
      <div class="status-ops-head">
        <span class="status-ops-title">${title}</span>
        ${running}
        <div class="status-ops-pills">${countPills}</div>
      </div>
      ${detailHtml ? `<div class="status-ops-details">${detailHtml}</div>` : ""}
    </div>`);
  }

  if (convertBusy) {
    document.body.classList.add("convert-queue-active");
    const jobHtml = jobs
      .map((job) => {
        const progress = job.convert_progress || {};
        let state;
        if (job.status === "converting") {
          const percent = progress.percent;
          state = percent != null ? `${percent}%` : "converting";
        } else {
          const position = Number(job.queue_position);
          state =
            Number.isFinite(position) && position > 0
              ? position === 1
                ? "next"
                : `#${position}`
              : "queued";
        }
        const action = job.mode === "flv" ? "convert" : "repair";
        const file = job.filename || "?";
        return `<div class="status-ops-job">
          <span class="status-ops-job-user">@${job.username || "?"}</span>
          <span class="status-ops-job-file" title="${file}">${file}</span>
          <span class="status-ops-job-meta">${action} · ${state}</span>
        </div>`;
      })
      .join("");
    blocks.push(`<div class="status-ops-block status-ops-block--convert">
      <div class="status-ops-head">
        <span class="status-ops-title">Convert</span>
        <div class="status-ops-pills">
          <span class="status-ops-pill"><span class="status-ops-pill-label">Active</span> ${active}/${max}</span>
          <span class="status-ops-pill"><span class="status-ops-pill-label">Queued</span> ${pending}</span>
        </div>
      </div>
      ${jobHtml ? `<div class="status-ops-jobs">${jobHtml}</div>` : ""}
    </div>`);
  } else {
    document.body.classList.remove("convert-queue-active");
  }

  if (!blocks.length) {
    statusOps.classList.add("hidden");
    statusOps.innerHTML = "";
    return;
  }

  statusOps.classList.remove("hidden");
  statusOps.innerHTML = blocks.join("");
}

export function renderSummaryChips(status) {
  if (!summaryFilters && !summaryMeta) return;
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

  const focusChip = selectedProfile
    ? `<button type="button" class="summary-chip summary-chip--focus" data-clear-focus="1" title="Clear focus">@${selectedProfile} <span aria-hidden="true">x</span></button>`
    : "";

  const filterChips = chips
    .map(
      ({ filter, label }) =>
        `<button type="button" class="summary-chip summary-chip--filter${statusFilter === filter ? " is-active" : ""}" data-filter="${filter}">${label}</button>`,
    )
    .join("");

  const hidePausedChip = `<button type="button" class="summary-chip summary-chip--toggle${hidePausedUsers ? " is-active" : ""}" data-toggle="hide-paused" title="Hide paused users from the All view">Hide paused</button>`;

  if (summaryFilters) {
    summaryFilters.innerHTML = `${filterChips}${hidePausedChip}${focusChip}`;
  }

  if (summaryMeta) {
    const facts = [];
    if (status.poll_in_progress) {
      facts.push(`<span class="summary-fact summary-fact--live">Poll running…</span>`);
    }
    const queue = status.convert_queue || {};
    const queueBusy = (queue.pending || 0) + (queue.active || 0);
    if (queueBusy > 0) {
      facts.push(
        `<span class="summary-fact summary-fact--live">Convert ${queue.active || 0}/${queue.max_concurrent || 1} · ${queue.pending || 0} queued</span>`,
      );
    }
    facts.push(
      `<span class="summary-fact">Last poll ${formatTimestamp(status.last_poll_at)}</span>`,
    );
    facts.push(`<span class="summary-fact">Next ${formatNextPoll(status)}</span>`);
    if (version) facts.push(`<span class="summary-fact">v${version}</span>`);
    if (status.ffmpeg?.path) {
      const sourceShort =
        status.ffmpeg.source === "vendor"
          ? "FFmpeg vendor"
          : status.ffmpeg.source === "system"
            ? "FFmpeg system"
            : "FFmpeg custom";
      const hevcShort = status.ffmpeg.hevc_capable ? "HEVC OK" : "HEVC !";
      const title = `${status.ffmpeg.path}\n${status.ffmpeg.version || ""}`;
      facts.push(
        `<span class="summary-fact" title="${title.replace(/"/g, "&quot;")}">${sourceShort} · ${hevcShort}</span>`,
      );
    }
    summaryMeta.innerHTML = facts.join('<span class="summary-fact-sep" aria-hidden="true">·</span>');
  }
}

export function setStatusFilterValue(filter) {
  setStatusFilter(filter);
  if (latestStatus) renderStatus(latestStatus);
}

export function loadStatusPreferences() {
  setHidePausedUsers(localStorage.getItem(STORAGE_HIDE_PAUSED_KEY) === "1");
  loadActivityPreferences();
}

export function saveHidePausedPreference(value) {
  setHidePausedUsers(value);
  localStorage.setItem(STORAGE_HIDE_PAUSED_KEY, value ? "1" : "0");
}

function renderStatusActions(row, status) {
  return buildUserActionButtons(row.username, status, row);
}

function formatStateLabel(row) {
  return row.state;
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
  } else {
    const libraryBytes = sumLibraryBytesForUser(row.username);
    if (libraryBytes > 0) {
      details.push(`${formatBytes(libraryBytes)} library`);
    }
  }
  const renamed = hasRenamedHandle(row.username, status);
  const tiktokHandle = currentTikTokHandle(row.username, status);
  const renameMarkup = renamed
    ? `<span class="status-rename">now @${tiktokHandle}</span>`
    : "";
  const tiktokLink = `<a class="profile-tiktok-link" href="${tiktokProfileUrl(tiktokHandle)}" target="_blank" rel="noopener noreferrer" title="Open TikTok profile">TikTok</a>`;
  const detailMarkup = details.length
    ? `<p class="status-line-detail">${details.join(" · ")}</p>`
    : "";

  return `
    <div class="status-line${isActive ? " status-line--active" : ""}${focused ? " status-line--focused" : ""}" data-username="${row.username}">
      <div class="status-line-body">
        <div class="status-line-main">
          ${profileLinkMarkup(row.username, { active: focused })}
          ${renameMarkup}
          ${tiktokLink}
          <span class="badge ${row.state}">${formatStateLabel(row)}</span>
        </div>
        ${detailMarkup}
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
  window.dispatchEvent(new CustomEvent("ttlr:profile-changed"));
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

  const mode = status.mode || "watchlist";
  if (statusMeta) {
    const bits = [mode];
    if (status.poll_in_progress) bits.push("polling");
    if (status.automatic_interval_minutes) {
      bits.push(`every ${status.automatic_interval_minutes} min`);
    }
    statusMeta.textContent = bits.join(" · ");
  }

  renderStatusOps(status);
  renderSummaryChips(status);
  renderActivityFeed(status.activity || []);
  renderTelegramUploads(status.telegram_uploads || []);
  syncRuntimeControls(status);

  if (!rows.length) {
    if (statusBoard) {
      statusBoard.innerHTML = `<p class="empty">${emptyUsersMessage(status)}</p>`;
    }
    window.dispatchEvent(new CustomEvent("ttlr:status-updated"));
    return;
  }

  renderStatusBoard(rows, status);
  window.dispatchEvent(new CustomEvent("ttlr:status-updated"));
}

export async function refreshStatus() {
  const status = await api("/api/status");
  renderStatus(status);
}

export function initStatusInteractions() {
  loadStatusPreferences();

  summaryFilters?.addEventListener("click", (event) => {
    const clearFocus = event.target.closest("[data-clear-focus]");
    if (clearFocus) {
      setSelectedProfile(null);
      return;
    }
    const toggle = event.target.closest("[data-toggle='hide-paused']");
    if (toggle) {
      saveHidePausedPreference(!hidePausedUsers);
      if (latestStatus) renderStatus(latestStatus);
      return;
    }
    const chip = event.target.closest("[data-filter]");
    if (!chip) return;
    setStatusFilterValue(chip.dataset.filter);
  });

  statusBoard?.addEventListener("click", handleStatusAction);

  window.addEventListener("ttlr:media-updated", () => {
    if (latestStatus) renderStatus(latestStatus);
  });
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
  await runUserAction(action, user, { onSuccess: refreshStatus });
}

// noop kept for media.js import compatibility
export function updateProfileBanner() {}
