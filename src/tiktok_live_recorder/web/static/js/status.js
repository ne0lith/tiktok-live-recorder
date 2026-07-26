import { api } from "./api.js";
import { renderActivityFeed } from "./activity.js";
import {
  basename,
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
  libraryState,
  expandStatusRowLimit,
  selectedProfile,
  setLatestStatus,
  setSelectedProfileValue,
  setStatusFilter,
  statusFilter,
  statusRowLimit,
  STATUS_ROW_LIMIT,
} from "./state.js";
import { renderTelegramUploads, syncRuntimeControls } from "./settings.js";

const statusBody = document.getElementById("status-body");
const statusMeta = document.getElementById("status-meta");
const statusMore = document.getElementById("status-more");
const pollSummary = document.getElementById("poll-summary");
const summaryChips = document.getElementById("summary-chips");
const statusCards = document.getElementById("status-cards");
const addUserForm = document.getElementById("add-user-form");
const forcePollBtn = document.getElementById("force-poll-btn");

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

function statusActionSlot(buttonHtml, placeholderLabel) {
  const content =
    buttonHtml || `<span class="action-placeholder">${placeholderLabel}</span>`;
  return `<div class="status-action-slot">${content}</div>`;
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

  const stopBtn = canStop
    ? `<button class="btn btn-danger btn-small" data-action="stop" data-user="${row.username}">Stop</button>`
    : null;

  const pauseBtn = paused
    ? `<button class="btn btn-ghost btn-small" data-action="resume" data-user="${row.username}">Resume</button>`
    : `<button class="btn btn-ghost btn-small" data-action="pause" data-user="${row.username}">Pause</button>`;

  const removeBtn = isWatchlist
    ? `<button class="btn btn-ghost btn-small" data-action="remove" data-user="${row.username}">Remove</button>`
    : null;

  const slots = [
    statusActionSlot(stopBtn, "Stop"),
    statusActionSlot(pauseBtn, "Resume"),
  ];
  if (isWatchlist) slots.push(statusActionSlot(removeBtn, "Remove"));

  const actionClass = isWatchlist
    ? "status-actions"
    : "status-actions status-actions--followers";
  return `<div class="${actionClass}">${slots.join("")}</div>`;
}

function renderStatusRowCells(row, status) {
  const sizeCell = row.output_path
    ? `<span class="output-cell" title="${row.output_path}"><span class="output-size">${formatBytes(row.bytes_written)}</span><span class="output-hint">${basename(row.output_path)}</span></span>`
    : formatBytes(row.bytes_written);
  const focused = usernamesMatch(row.username, selectedProfile);
  const highlight =
    row.state === "recording" || row.state === "live" ? " status-row--active" : "";
  const focusClass = focused ? " status-row--focused" : "";
  return `
    <tr class="status-row${highlight}${focusClass}" data-username="${row.username}">
      <td class="username">${profileLinkMarkup(row.username, {
        active: focused,
      })}</td>
      <td><span class="badge ${row.state}">${row.state}</span></td>
      <td class="col-room">${row.room_id || "-"}</td>
      <td class="col-elapsed">${formatDuration(row.elapsed_seconds)}</td>
      <td class="col-size">${sizeCell}</td>
      <td class="col-actions">${renderStatusActions(row, status)}</td>
    </tr>
  `;
}

function updateStatusRow(tr, row, status) {
  const focused = usernamesMatch(row.username, selectedProfile);
  tr.className = `status-row${
    row.state === "recording" || row.state === "live" ? " status-row--active" : ""
  }${focused ? " status-row--focused" : ""}`;
  const badge = tr.querySelector(".badge");
  if (badge) {
    badge.textContent = row.state;
    badge.className = `badge ${row.state}`;
  }
  const room = tr.querySelector(".col-room");
  if (room) room.textContent = row.room_id || "-";
  const elapsed = tr.querySelector(".col-elapsed");
  if (elapsed) elapsed.textContent = formatDuration(row.elapsed_seconds);
  const sizeCell = tr.children[4];
  if (sizeCell) {
    if (row.output_path) {
      sizeCell.innerHTML = `<span class="output-cell" title="${row.output_path}"><span class="output-size">${formatBytes(row.bytes_written)}</span><span class="output-hint">${basename(row.output_path)}</span></span>`;
    } else {
      sizeCell.textContent = formatBytes(row.bytes_written);
    }
  }
  const actions = tr.querySelector(".col-actions");
  if (actions) actions.innerHTML = renderStatusActions(row, status);
  const link = tr.querySelector(".profile-link");
  if (link) link.classList.toggle("is-active", focused);
}

function updateStatusTable(rows, status) {
  if (!statusBody) return;
  const existing = new Map();
  statusBody.querySelectorAll("tr.status-row").forEach((tr) => {
    existing.set(tr.dataset.username, tr);
  });
  const seen = new Set();
  for (const row of rows) {
    seen.add(row.username);
    let tr = existing.get(row.username);
    if (!tr) {
      const temp = document.createElement("tbody");
      temp.innerHTML = renderStatusRowCells(row, status);
      tr = temp.firstElementChild;
      statusBody.appendChild(tr);
    } else {
      updateStatusRow(tr, row, status);
    }
  }
  existing.forEach((tr, username) => {
    if (!seen.has(username)) tr.remove();
  });
}

function renderStatusCard(row, status) {
  const focused = usernamesMatch(row.username, selectedProfile);
  const highlight =
    row.state === "recording" || row.state === "live" ? " status-card--active" : "";
  const focusClass = focused ? " status-card--focused" : "";
  return `
    <article class="status-card${highlight}${focusClass}">
      <div class="status-card-head">
        ${profileLinkMarkup(row.username, { active: focused })}
        <span class="badge ${row.state}">${row.state}</span>
      </div>
      <div class="status-card-meta">
        <span>Room ${row.room_id || "-"}</span>
        <span>${formatDuration(row.elapsed_seconds)}</span>
        <span>${formatBytes(row.bytes_written)}</span>
      </div>
      ${row.output_path ? `<p class="status-card-file" title="${row.output_path}">${basename(row.output_path)}</p>` : ""}
      <div class="status-card-actions">${renderStatusActions(row, status)}</div>
    </article>
  `;
}

export function scrollToFocusedUser() {
  if (!selectedProfile) return;
  const section = document.querySelector(
    `.user-section[data-username="${CSS.escape(selectedProfile)}"]`,
  );
  if (section) {
    section.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  const row = statusBody?.querySelector(
    `tr.status-row[data-username="${CSS.escape(selectedProfile)}"]`,
  );
  row?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

export function setSelectedProfile(username) {
  setSelectedProfileValue(username ? normalizeUsername(username) : null);
  const base = `${window.location.pathname}${window.location.search}`;
  if (selectedProfile) {
    window.history.replaceState(null, "", `${base}#user/${encodeURIComponent(selectedProfile)}`);
    libraryState.expandedUsers.add(selectedProfile);
    libraryState.visibleCounts.delete(selectedProfile);
    if (libraryState.viewMode === "recent") {
      libraryState.viewMode = "by-user";
      import("./media.js").then((m) => {
        m.saveLibraryViewMode("by-user");
        m.syncLibraryViewButtons();
      });
    }
  } else {
    window.history.replaceState(null, "", base);
  }
  if (latestStatus) renderStatus(latestStatus);
  else renderSummaryChips(latestStatus || {});
  if (Object.keys(latestMedia).length) {
    import("./media.js").then((m) => m.renderMedia(latestMedia));
  }
  if (selectedProfile) {
    requestAnimationFrame(() => scrollToFocusedUser());
  }
}

export function readProfileFromHash() {
  const match = window.location.hash.match(/^#user\/(.+)$/);
  if (match) {
    setSelectedProfileValue(normalizeUsername(decodeURIComponent(match[1])));
    libraryState.expandedUsers.add(selectedProfile);
  }
}

export function renderStatus(status) {
  setLatestStatus(status);
  applyModeUI(status);
  syncPollUI(status);
  let rows = deriveRows(status);
  const totalRows = rows.length;
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

  if (!rows.length) {
    const empty = emptyUsersMessage(status);
    if (statusBody) statusBody.innerHTML = `<tr><td colspan="6" class="empty">${empty}</td></tr>`;
    if (statusCards) statusCards.innerHTML = `<p class="empty">${empty}</p>`;
    if (statusMore) statusMore.classList.add("hidden");
    return;
  }

  const limited = rows.length > statusRowLimit;
  const visibleRows = limited ? rows.slice(0, statusRowLimit) : rows;
  updateStatusTable(visibleRows, status);

  if (statusMore) {
    if (limited) {
      statusMore.classList.remove("hidden");
      statusMore.textContent = `Showing ${statusRowLimit} of ${totalRows} users`;
    } else {
      statusMore.classList.add("hidden");
    }
  }

  if (statusCards) {
    statusCards.innerHTML = visibleRows.map((row) => renderStatusCard(row, status)).join("");
  }
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

  statusMore?.addEventListener("click", () => {
    if (!latestStatus) return;
    expandStatusRowLimit(deriveRows(latestStatus).length);
    renderStatus(latestStatus);
  });

  statusBody?.addEventListener("click", handleStatusAction);
  statusCards?.addEventListener("click", handleStatusAction);
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
