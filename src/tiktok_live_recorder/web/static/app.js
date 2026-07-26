const statusBody = document.getElementById("status-body");
const statusMeta = document.getElementById("status-meta");
const mediaLibrary = document.getElementById("media-library");
const librarySummary = document.getElementById("library-summary");
const mediaSearch = document.getElementById("media-search");
const mediaPlayer = document.getElementById("media-player");
const mediaPlayerVideo = document.getElementById("media-player-video");
const playerTitle = document.getElementById("player-title");
const playerMeta = document.getElementById("player-meta");
const profileBanner = document.getElementById("profile-banner");
const profileTitle = document.getElementById("profile-title");
const profileMeta = document.getElementById("profile-meta");
const profileBadge = document.getElementById("profile-badge");
const profileTiktokLink = document.getElementById("profile-tiktok-link");
const settingsPanel = document.getElementById("settings-panel");
const settingsToggle = document.getElementById("settings-toggle");
const pollSummary = document.getElementById("poll-summary");
const addUserForm = document.getElementById("add-user-form");
const toast = document.getElementById("toast");

let latestStatus = null;
let pendingMedia = null;
let latestMedia = {};
let selectedProfile = null;
const libraryState = {
  expandedUsers: new Set(),
  visibleCounts: new Map(),
  playingUrl: null,
};

const INITIAL_VISIBLE = 8;
const LOAD_MORE_STEP = 20;
const API_TIMEOUT_MS = 12000;

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 2600);
}

function parseApiError(text, status) {
  try {
    const data = JSON.parse(text);
    const detail = data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => item.msg || item.message || JSON.stringify(item))
        .join("; ");
    }
  } catch {
    // not JSON
  }
  return text || `Request failed (${status})`;
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      signal: controller.signal,
      ...options,
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(parseApiError(detail, response.status));
    }
    if (response.status === 204) return null;
    return response.json();
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("Request timed out — recorder may be busy or network is down");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDuration(seconds) {
  if (seconds == null) return "-";
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatTimestamp(epoch) {
  if (!epoch) return "Never";
  return new Date(epoch * 1000).toLocaleString();
}

function basename(path) {
  if (!path) return "";
  const parts = String(path).split(/[/\\]/);
  return parts[parts.length - 1] || path;
}

function applyModeUI(status) {
  const mode = status?.mode || "watchlist";
  document.body.dataset.mode = mode;
  addUserForm.classList.toggle("hidden", mode !== "watchlist");
}

function emptyUsersMessage(status) {
  if (selectedProfile) {
    return "This user is not in the current list.";
  }
  if (status.mode === "followers") {
    return "No followers loaded yet.";
  }
  if (status.mode === "automatic") {
    return "No tracked user yet.";
  }
  return "No users in watchlist yet.";
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
          if (text.includes("(") || text.includes(" ")) {
            return text.startsWith("@") ? text : text;
          }
          return text.startsWith("@") ? text : `@${text}`;
        })
        .join(", ");
      return `<div class="poll-group"><span class="poll-group-label">${name}</span> ${values}</div>`;
    })
    .join("");

  pollSummary.classList.remove("hidden");
  pollSummary.innerHTML = `${label}${chunks}`;
}

function normalizeUsername(username) {
  return String(username || "")
    .replace(/^@+/, "")
    .trim();
}

function usernamesMatch(a, b) {
  return normalizeUsername(a).toLowerCase() === normalizeUsername(b).toLowerCase();
}

function setSelectedProfile(username) {
  selectedProfile = username ? normalizeUsername(username) : null;
  const base = `${window.location.pathname}${window.location.search}`;
  if (selectedProfile) {
    window.history.replaceState(null, "", `${base}#user/${encodeURIComponent(selectedProfile)}`);
    libraryState.expandedUsers.add(selectedProfile);
    libraryState.visibleCounts.delete(selectedProfile);
  } else {
    window.history.replaceState(null, "", base);
  }
  document.body.classList.toggle("profile-active", Boolean(selectedProfile));
  updateProfileBanner();
  if (latestStatus) renderStatus(latestStatus);
  if (Object.keys(latestMedia).length) renderMedia(latestMedia);
  if (selectedProfile) {
    requestAnimationFrame(() => {
      profileBanner.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
}

function readProfileFromHash() {
  const match = window.location.hash.match(/^#user\/(.+)$/);
  if (match) {
    selectedProfile = normalizeUsername(decodeURIComponent(match[1]));
    document.body.classList.add("profile-active");
    libraryState.expandedUsers.add(selectedProfile);
  }
}

function findProfileRow(status) {
  if (!selectedProfile) return null;
  return deriveRows(status).find((row) => usernamesMatch(row.username, selectedProfile));
}

function tiktokProfileUrl(username) {
  return `https://tiktok.com/@${encodeURIComponent(normalizeUsername(username))}`;
}

function updateProfileBanner() {
  if (!selectedProfile) {
    profileBanner.classList.add("hidden");
    return;
  }

  const row = latestStatus ? findProfileRow(latestStatus) : null;
  const mediaItems = Object.entries(latestMedia).find(([username]) =>
    usernamesMatch(username, selectedProfile),
  )?.[1];

  profileBanner.classList.remove("hidden");
  profileTitle.textContent = `@${selectedProfile}`;
  profileTiktokLink.href = tiktokProfileUrl(selectedProfile);
  profileBadge.textContent = row?.state || "offline";
  profileBadge.className = `badge ${row?.state || "offline"}`;

  const bits = [];
  if (row?.room_id) bits.push(`room ${row.room_id}`);
  if (row?.elapsed_seconds != null) bits.push(formatDuration(row.elapsed_seconds));
  if (row?.bytes_written != null) bits.push(formatBytes(row.bytes_written));
  if (row?.output_path) bits.push(basename(row.output_path));
  if (mediaItems?.length) {
    bits.push(`${mediaItems.length} recording${mediaItems.length === 1 ? "" : "s"}`);
    bits.push(formatBytes(sumMediaSize(mediaItems)));
  }
  profileMeta.textContent = bits.length ? bits.join(" · ") : "Profile view";
}

function filterByProfile(media) {
  if (!selectedProfile) return media;
  const match = Object.entries(media || {}).find(([username]) =>
    usernamesMatch(username, selectedProfile),
  );
  return match ? { [match[0]]: match[1] } : {};
}

function profileLinkMarkup(username, { active = false } = {}) {
  return `<button type="button" class="profile-link${active ? " is-active" : ""}" data-profile="${username}">@${username}</button>`;
}

function deriveRows(status) {
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
    const row = ensure(username, entry.status || "recording");
    row.state = entry.status || row.state;
    row.room_id = entry.room_id || row.room_id;
    row.elapsed_seconds = entry.elapsed_seconds;
    row.bytes_written = entry.bytes_written;
    row.output_path = entry.output_path || row.output_path;
  });

  return Array.from(rows.values()).sort((a, b) =>
    a.username.localeCompare(b.username),
  );
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
  if (isWatchlist) {
    slots.push(statusActionSlot(removeBtn, "Remove"));
  }

  const actionClass = isWatchlist
    ? "status-actions"
    : "status-actions status-actions--followers";
  return `<div class="${actionClass}">${slots.join("")}</div>`;
}

function renderStatus(status) {
  latestStatus = status;
  applyModeUI(status);
  let rows = deriveRows(status);
  if (selectedProfile) {
    rows = rows.filter((row) => usernamesMatch(row.username, selectedProfile));
  }

  const scope = selectedProfile ? `@${selectedProfile}` : "All users";
  const pollLabel = status.poll_label ? ` · ${status.poll_label}` : "";
  statusMeta.textContent = `${scope} · ${status.mode}${pollLabel} · last poll ${formatTimestamp(
    status.last_poll_at,
  )} · interval ${status.automatic_interval_minutes} min`;

  renderPollSummary(status);
  updateProfileBanner();
  renderTelegramUploads(status.telegram_uploads || []);
  syncRuntimeControls(status);

  if (!rows.length) {
    statusBody.innerHTML = `<tr><td colspan="6" class="empty">${emptyUsersMessage(status)}</td></tr>`;
    return;
  }

  statusBody.innerHTML = rows
    .map((row) => {
      const sizeCell = row.output_path
        ? `<span title="${row.output_path}">${formatBytes(row.bytes_written)}<span class="output-hint"> · ${basename(row.output_path)}</span></span>`
        : formatBytes(row.bytes_written);
      return `
        <tr>
          <td class="username">${profileLinkMarkup(row.username, {
            active: usernamesMatch(row.username, selectedProfile),
          })}</td>
          <td><span class="badge ${row.state}">${row.state}</span></td>
          <td>${row.room_id || "-"}</td>
          <td>${formatDuration(row.elapsed_seconds)}</td>
          <td>${sizeCell}</td>
          <td class="col-actions">${renderStatusActions(row, status)}</td>
        </tr>
      `;
    })
    .join("");
}

function isAnyMediaPlaying() {
  return Boolean(
    mediaPlayerVideo &&
      mediaPlayerVideo.src &&
      !mediaPlayerVideo.paused &&
      !mediaPlayerVideo.ended,
  );
}

function mediaItemMeta(item) {
  return `${formatBytes(item.size)} · ${formatTimestamp(item.modified_at)}${
    item.in_progress ? " · in progress" : ""
  }${item.source === "legacy" ? " · legacy" : ""}`;
}

function sumMediaSize(items) {
  return items.reduce((total, item) => total + (item.size || 0), 0);
}

function filterMedia(media, query) {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return media;
  }

  const filtered = {};
  for (const [username, items] of Object.entries(media || {})) {
    const usernameMatch = username.toLowerCase().includes(needle);
    const matchedItems = usernameMatch
      ? items
      : items.filter((item) => item.filename.toLowerCase().includes(needle));
    if (matchedItems.length) {
      filtered[username] = matchedItems;
    }
  }
  return filtered;
}

function updateLibrarySummary(media) {
  const usernames = Object.keys(media || {});
  const fileCount = usernames.reduce(
    (total, username) => total + media[username].length,
    0,
  );
  const totalSize = usernames.reduce(
    (total, username) => total + sumMediaSize(media[username]),
    0,
  );
  if (selectedProfile) {
    librarySummary.textContent = `${fileCount} recording${fileCount === 1 ? "" : "s"} · ${formatBytes(totalSize)}`;
    return;
  }
  librarySummary.textContent = `${fileCount} recording${fileCount === 1 ? "" : "s"} · ${usernames.length} user${usernames.length === 1 ? "" : "s"} · ${formatBytes(totalSize)}`;
}

function getVisibleCount(username, total) {
  if (!libraryState.visibleCounts.has(username)) {
    libraryState.visibleCounts.set(username, Math.min(INITIAL_VISIBLE, total));
  }
  return Math.min(libraryState.visibleCounts.get(username), total);
}

function setExpanded(username, expanded) {
  if (expanded) {
    libraryState.expandedUsers.add(username);
  } else {
    libraryState.expandedUsers.delete(username);
  }
}

function playMedia(item, username) {
  libraryState.playingUrl = item.url;
  setExpanded(username, true);
  playerTitle.textContent = `@${username} · ${item.filename}`;
  playerMeta.textContent = mediaItemMeta(item);
  mediaPlayer.classList.remove("hidden");
  const targetUrl = new URL(item.url, window.location.origin).href;
  if (mediaPlayerVideo.src !== targetUrl) {
    mediaPlayerVideo.src = item.url;
  }
  mediaPlayerVideo.play().catch(() => {});
  const section = mediaLibrary.querySelector(
    `.user-section[data-username="${CSS.escape(username)}"]`,
  );
  section?.classList.add("expanded");
  highlightActiveRow();
}

function closePlayer() {
  mediaPlayerVideo.pause();
  mediaPlayerVideo.removeAttribute("src");
  mediaPlayerVideo.load();
  libraryState.playingUrl = null;
  mediaPlayer.classList.add("hidden");
  highlightActiveRow();
}

function highlightActiveRow() {
  for (const row of mediaLibrary.querySelectorAll(".media-row")) {
    row.classList.toggle("is-active", row.dataset.url === libraryState.playingUrl);
  }
}

function createMediaRow(item, username) {
  const row = document.createElement("div");
  row.className = "media-row";
  row.dataset.url = item.url;
  row.dataset.username = username;

  const main = document.createElement("button");
  main.type = "button";
  main.className = "media-row-main";

  const name = document.createElement("span");
  name.className = "media-row-name";
  name.title = item.filename;
  name.textContent = item.filename;

  const meta = document.createElement("span");
  meta.className = "media-row-meta";
  meta.textContent = mediaItemMeta(item);

  const play = document.createElement("span");
  play.className = "media-row-play";
  play.textContent = "Play";

  main.append(name, meta, play);
  main.addEventListener("click", () => playMedia(item, username));

  const actions = document.createElement("div");
  actions.className = "media-row-actions";

  const download = document.createElement("a");
  download.className = "btn btn-ghost btn-small";
  download.href = item.url;
  download.download = item.filename;
  download.textContent = "Download";
  download.addEventListener("click", (event) => event.stopPropagation());

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "btn btn-ghost btn-small media-delete-btn";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", async (event) => {
    event.stopPropagation();
    if (!confirm(`Delete ${item.filename}?`)) return;
    try {
      await deleteMediaItem(username, item);
      showToast(`Deleted ${item.filename}`);
      if (libraryState.playingUrl === item.url) {
        closePlayer();
      }
      await refreshMedia({ force: true });
    } catch (error) {
      showToast(error.message);
    }
  });

  actions.append(download, deleteBtn);
  row.append(main, actions);
  return row;
}

async function deleteMediaItem(username, item) {
  const encodedUser = encodeURIComponent(username);
  const encodedFile = encodeURIComponent(item.filename);
  const path =
    item.source === "legacy"
      ? `/api/media/${encodedUser}/legacy/${encodedFile}`
      : `/api/media/${encodedUser}/${encodedFile}`;
  await api(path, { method: "DELETE" });
}

function renderUserSection(username, items) {
  let section = mediaLibrary.querySelector(
    `.user-section[data-username="${CSS.escape(username)}"]`,
  );
  if (!section) {
    section = document.createElement("section");
    section.className = "user-section";
    section.dataset.username = username;
    section.innerHTML = `
      <button class="user-section-toggle" type="button">
        <span class="user-section-title"></span>
        <span class="user-section-count"></span>
        <span class="user-section-chevron" aria-hidden="true">'</span>
      </button>
      <div class="user-section-body">
        <div class="media-list"></div>
        <div class="user-section-footer hidden">
          <button class="btn btn-ghost btn-small show-more" type="button"></button>
        </div>
      </div>
    `;
    section.querySelector(".user-section-toggle").addEventListener("click", () => {
      const expanded = section.classList.toggle("expanded");
      setExpanded(username, expanded);
    });
    section.querySelector(".show-more").addEventListener("click", (event) => {
      event.stopPropagation();
      const current = getVisibleCount(username, items.length);
      libraryState.visibleCounts.set(
        username,
        Math.min(current + LOAD_MORE_STEP, items.length),
      );
      renderMedia(latestMedia);
    });
    mediaLibrary.append(section);
  }

  const expanded = libraryState.expandedUsers.has(username);
  section.classList.toggle("expanded", expanded);
  const title = section.querySelector(".user-section-title");
  title.textContent = `@${username}`;
  title.classList.add("profile-link");
  title.dataset.profile = username;
  title.classList.toggle("is-active", usernamesMatch(username, selectedProfile));
  if (!title.dataset.profileBound) {
    title.dataset.profileBound = "true";
    title.addEventListener("click", (event) => {
      event.stopPropagation();
      setSelectedProfile(username);
    });
  }
  section.querySelector(".user-section-count").textContent = `${items.length} recording${
    items.length === 1 ? "" : "s"
  } · ${formatBytes(sumMediaSize(items))}`;

  const visibleCount = getVisibleCount(username, items.length);
  const list = section.querySelector(".media-list");
  list.replaceChildren();
  for (const item of items.slice(0, visibleCount)) {
    const row = createMediaRow(item, username);
    if (item.url === libraryState.playingUrl) {
      row.classList.add("is-active");
    }
    list.append(row);
  }

  const footer = section.querySelector(".user-section-footer");
  const showMore = section.querySelector(".show-more");
  if (visibleCount < items.length) {
    footer.classList.remove("hidden");
    showMore.textContent = `Show ${items.length - visibleCount} more`;
  } else {
    footer.classList.add("hidden");
  }

  return section;
}

function renderMedia(media) {
  latestMedia = media || {};
  const query = mediaSearch.value || "";
  let filtered = filterMedia(latestMedia, query);
  filtered = filterByProfile(filtered);
  if (selectedProfile) {
    mediaSearch.placeholder = `Search @${selectedProfile} recordings…`;
  } else {
    mediaSearch.placeholder = "Search by username or filename…";
  }
  const usernames = Object.keys(filtered).sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: "base" }),
  );

  updateLibrarySummary(filtered);

  if (!usernames.length) {
    if (!isAnyMediaPlaying()) {
      mediaLibrary.innerHTML = selectedProfile
        ? '<p class="empty">No recordings for this user yet.</p>'
        : query
          ? '<p class="empty">No recordings match your search.</p>'
          : '<p class="empty">No recordings yet.</p>';
    }
    updateLibrarySummary(filtered);
    updateProfileBanner();
    return;
  }

  mediaLibrary.querySelector(".empty")?.remove();
  const seenUsers = new Set();

  for (const username of usernames) {
    seenUsers.add(username);
    renderUserSection(username, filtered[username]);
  }

  for (const section of mediaLibrary.querySelectorAll(".user-section")) {
    const username = section.dataset.username;
    if (!seenUsers.has(username)) {
      section.remove();
    }
  }

  if (usernames.length === 1 && (!query || selectedProfile)) {
    setExpanded(usernames[0], true);
    mediaLibrary.querySelector(
      `.user-section[data-username="${CSS.escape(usernames[0])}"]`,
    )?.classList.add("expanded");
  }

  updateProfileBanner();
}

function maybeApplyPendingMedia() {
  if (pendingMedia && !isAnyMediaPlaying()) {
    const media = pendingMedia;
    pendingMedia = null;
    renderMedia(media);
  }
}

async function refreshStatus() {
  const status = await api("/api/status");
  renderStatus(status);
}

async function refreshMedia({ force = false } = {}) {
  const media = await api("/api/media");
  if (!force && isAnyMediaPlaying()) {
    pendingMedia = media;
    return;
  }
  pendingMedia = null;
  renderMedia(media);
}

statusBody.addEventListener("click", async (event) => {
  const profileButton = event.target.closest("button[data-profile]");
  if (profileButton) {
    setSelectedProfile(profileButton.dataset.profile);
    return;
  }

  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action, user } = button.dataset;
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
});

document.getElementById("add-user-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("add-user-input");
  const username = input.value.trim();
  if (!username) return;
  try {
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({ username }),
    });
    input.value = "";
    showToast(`Added @${username.replace(/^@/, "")}`);
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("force-poll-btn").addEventListener("click", async () => {
  try {
    await api("/api/poll", { method: "POST" });
    showToast("Poll requested");
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("refresh-media-btn").addEventListener("click", async () => {
  try {
    await refreshMedia({ force: true });
    showToast("Media refreshed");
  } catch (error) {
    showToast(error.message);
  }
});

mediaSearch.addEventListener("input", () => {
  renderMedia(latestMedia);
});

document.getElementById("player-close").addEventListener("click", closePlayer);

mediaPlayerVideo.addEventListener("pause", maybeApplyPendingMedia);
mediaPlayerVideo.addEventListener("ended", maybeApplyPendingMedia);

document.getElementById("profile-back").addEventListener("click", () => {
  setSelectedProfile(null);
});

window.addEventListener("hashchange", () => {
  const match = window.location.hash.match(/^#user\/(.+)$/);
  if (match) {
    selectedProfile = normalizeUsername(decodeURIComponent(match[1]));
    document.body.classList.add("profile-active");
    libraryState.expandedUsers.add(selectedProfile);
  } else {
    selectedProfile = null;
    document.body.classList.remove("profile-active");
  }
  updateProfileBanner();
  if (latestStatus) renderStatus(latestStatus);
  if (Object.keys(latestMedia).length) renderMedia(latestMedia);
});

document.getElementById("settings-toggle").addEventListener("click", async () => {
  const opening = settingsPanel.classList.contains("hidden");
  settingsPanel.classList.toggle("hidden");
  settingsToggle.classList.toggle("is-active", opening);
  if (opening) {
    try {
      await loadSettings();
    } catch (error) {
      showToast(error.message);
    }
    settingsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});

function syncRuntimeControls(status) {
  const intervalInput = document.getElementById("interval-input");
  const telegramEnabled = document.getElementById("telegram-enabled");
  if (document.activeElement !== intervalInput) {
    intervalInput.value = String(status.automatic_interval_minutes ?? 5);
  }
  if (document.activeElement !== telegramEnabled) {
    telegramEnabled.checked = Boolean(status.use_telegram);
  }
}

function renderTelegramUploads(uploads) {
  const container = document.getElementById("telegram-uploads");
  const list = document.getElementById("telegram-uploads-list");
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

async function loadSettings() {
  const [cookies, telegram, runtime] = await Promise.all([
    api("/api/settings/cookies"),
    api("/api/settings/telegram"),
    api("/api/settings/runtime"),
  ]);
  document.getElementById("cookies-editor").value = JSON.stringify(
    cookies.cookies || {},
    null,
    2,
  );
  document.getElementById("telegram-editor").value = JSON.stringify(
    telegram.telegram || {},
    null,
    2,
  );
  document.getElementById("interval-input").value = String(
    runtime.automatic_interval_minutes ?? 5,
  );
  document.getElementById("telegram-enabled").checked = Boolean(runtime.use_telegram);
}

document.getElementById("save-runtime-btn").addEventListener("click", async () => {
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

document.getElementById("record-now-btn").addEventListener("click", async () => {
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

document.getElementById("save-cookies-btn").addEventListener("click", async () => {
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

document.getElementById("save-telegram-btn").addEventListener("click", async () => {
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

async function boot() {
  readProfileFromHash();
  try {
    await Promise.all([refreshStatus(), refreshMedia(), loadSettings()]);
  } catch (error) {
    showToast(error.message);
  }
  setInterval(refreshStatus, 2500);
  setInterval(() => refreshMedia(), 60000);
}

boot();
