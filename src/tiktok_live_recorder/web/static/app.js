const statusBody = document.getElementById("status-body");
const statusMeta = document.getElementById("status-meta");
const mediaLibrary = document.getElementById("media-library");
const librarySummary = document.getElementById("library-summary");
const mediaSearch = document.getElementById("media-search");
const mediaPlayer = document.getElementById("media-player");
const mediaPlayerVideo = document.getElementById("media-player-video");
const playerTitle = document.getElementById("player-title");
const playerMeta = document.getElementById("player-meta");
const toast = document.getElementById("toast");

let latestStatus = null;
let pendingMedia = null;
let latestMedia = {};
const libraryState = {
  expandedUsers: new Set(),
  visibleCounts: new Map(),
  playingUrl: null,
};

const INITIAL_VISIBLE = 8;
const LOAD_MORE_STEP = 20;

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
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
  });

  return Array.from(rows.values()).sort((a, b) =>
    a.username.localeCompare(b.username),
  );
}

function renderStatus(status) {
  latestStatus = status;
  const rows = deriveRows(status);
  statusMeta.textContent = `${status.mode} · last poll ${formatTimestamp(
    status.last_poll_at,
  )} · interval ${status.automatic_interval_minutes} min`;

  if (!rows.length) {
    statusBody.innerHTML =
      '<tr><td colspan="6" class="empty">No users in watchlist yet.</td></tr>';
    return;
  }

  statusBody.innerHTML = rows
    .map((row) => {
      const paused = (status.paused || [])
        .map((u) => u.toLowerCase())
        .includes(row.username.toLowerCase());
      const isWatchlist = status.mode === "watchlist";
      const actions = [];
      if (row.state === "recording" || row.state === "converting" || row.state === "stopping") {
        actions.push(
          `<button class="btn btn-danger btn-small" data-action="stop" data-user="${row.username}">Stop</button>`,
        );
      }
      if (paused) {
        actions.push(
          `<button class="btn btn-ghost btn-small" data-action="resume" data-user="${row.username}">Resume</button>`,
        );
      } else {
        actions.push(
          `<button class="btn btn-ghost btn-small" data-action="pause" data-user="${row.username}">Pause</button>`,
        );
      }
      if (isWatchlist) {
        actions.push(
          `<button class="btn btn-ghost btn-small" data-action="remove" data-user="${row.username}">Remove</button>`,
        );
      }
      return `
        <tr>
          <td class="username">@${row.username}</td>
          <td><span class="badge ${row.state}">${row.state}</span></td>
          <td>${row.room_id || "-"}</td>
          <td>${formatDuration(row.elapsed_seconds)}</td>
          <td>${formatBytes(row.bytes_written)}</td>
          <td><div class="actions">${actions.join("")}</div></td>
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
  const row = document.createElement("button");
  row.type = "button";
  row.className = "media-row";
  row.dataset.url = item.url;
  row.dataset.username = username;

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

  row.append(name, meta, play);
  row.addEventListener("click", () => playMedia(item, username));
  return row;
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
  section.querySelector(".user-section-title").textContent = `@${username}`;
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
  const filtered = filterMedia(latestMedia, query);
  const usernames = Object.keys(filtered).sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: "base" }),
  );

  updateLibrarySummary(filtered);

  if (!usernames.length) {
    if (!isAnyMediaPlaying()) {
      mediaLibrary.innerHTML = query
        ? '<p class="empty">No recordings match your search.</p>'
        : '<p class="empty">No recordings yet.</p>';
    }
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

  if (usernames.length === 1 && !query) {
    setExpanded(usernames[0], true);
    mediaLibrary.querySelector(
      `.user-section[data-username="${CSS.escape(usernames[0])}"]`,
    )?.classList.add("expanded");
  }
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

document.getElementById("settings-toggle").addEventListener("click", () => {
  document.getElementById("settings-panel").classList.toggle("hidden");
});

async function loadSettings() {
  const [cookies, telegram] = await Promise.all([
    api("/api/settings/cookies"),
    api("/api/settings/telegram"),
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
}

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
  try {
    await Promise.all([refreshStatus(), refreshMedia(), loadSettings()]);
  } catch (error) {
    showToast(error.message);
  }
  setInterval(refreshStatus, 2500);
  setInterval(() => refreshMedia(), 60000);
}

boot();
