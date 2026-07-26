import { api, showToast } from "./api.js";
import { formatBytes, formatTimestamp } from "./format.js";
import {
  STORAGE_SORT_KEY,
  latestMedia,
  libraryState,
  pendingMedia,
  setLatestMedia,
  setPendingMedia,
} from "./state.js";

const libraryBody = document.getElementById("library-body");
const mediaLibrary = document.getElementById("media-library");
const librarySummary = document.getElementById("library-summary");
const mediaSearch = document.getElementById("media-search");
const mediaPlayer = document.getElementById("media-player");
const mediaPlayerVideo = document.getElementById("media-player-video");
const playerTitle = document.getElementById("player-title");
const playerMeta = document.getElementById("player-meta");

export function loadLibraryPreferences() {
  const savedSort = localStorage.getItem(STORAGE_SORT_KEY);
  if (savedSort) libraryState.sortMode = savedSort;
  const sortSelect = document.getElementById("library-sort");
  if (sortSelect) sortSelect.value = libraryState.sortMode;
}

export function saveLibrarySortMode(mode) {
  libraryState.sortMode = mode;
  localStorage.setItem(STORAGE_SORT_KEY, mode);
}

function isAnyMediaPlaying() {
  return Boolean(
    mediaPlayerVideo &&
      mediaPlayerVideo.src &&
      !mediaPlayerVideo.paused &&
      !mediaPlayerVideo.ended,
  );
}

function isPlayerActive() {
  return Boolean(
    mediaPlayerVideo &&
      mediaPlayerVideo.src &&
      !mediaPlayerVideo.ended &&
      mediaPlayer &&
      !mediaPlayer.classList.contains("hidden"),
  );
}

function shouldDeferMediaRender() {
  return isPlayerActive();
}

function mediaItemMeta(item) {
  const statusBits = [];
  if (item.in_progress) statusBits.push("in progress");
  else if (item.needs_convert) statusBits.push("needs convert");
  const statusSuffix = statusBits.length ? ` · ${statusBits.join(", ")}` : "";
  return `${formatBytes(item.size)} · ${formatTimestamp(item.modified_at)}${statusSuffix}${
    item.source === "legacy" ? " · legacy" : ""
  }`;
}

function sumMediaSize(items) {
  return items.reduce((total, item) => total + (item.size || 0), 0);
}

function filterMedia(media, query) {
  const needle = query.trim().toLowerCase();
  if (!needle) return media;

  const filtered = {};
  for (const [username, items] of Object.entries(media || {})) {
    const usernameMatch = username.toLowerCase().includes(needle);
    const matchedItems = usernameMatch
      ? items
      : items.filter((item) => item.filename.toLowerCase().includes(needle));
    if (matchedItems.length) filtered[username] = matchedItems;
  }
  return filtered;
}

function updateLibrarySummary(media) {
  const source = latestMedia || media || {};
  const usernames = Object.keys(source);
  const fileCount = usernames.reduce((total, username) => total + source[username].length, 0);
  const totalSize = usernames.reduce(
    (total, username) => total + sumMediaSize(source[username]),
    0,
  );
  if (!librarySummary) return;
  librarySummary.textContent = `${fileCount} recording${fileCount === 1 ? "" : "s"} · ${usernames.length} user${usernames.length === 1 ? "" : "s"} · ${formatBytes(totalSize)}`;
}

export function flattenAndSortMedia(media) {
  const rows = [];
  for (const [username, items] of Object.entries(media || {})) {
    for (const item of items) rows.push({ item, username });
  }

  const sortMode = libraryState.sortMode;
  rows.sort((a, b) => {
    if (a.item.in_progress !== b.item.in_progress) {
      return a.item.in_progress ? -1 : 1;
    }
    if (sortMode === "oldest") {
      return (a.item.modified_at || 0) - (b.item.modified_at || 0);
    }
    if (sortMode === "largest") {
      return (b.item.size || 0) - (a.item.size || 0);
    }
    if (sortMode === "user") {
      const userCmp = a.username.localeCompare(b.username, undefined, { sensitivity: "base" });
      if (userCmp !== 0) return userCmp;
      return (b.item.modified_at || 0) - (a.item.modified_at || 0);
    }
    return (b.item.modified_at || 0) - (a.item.modified_at || 0);
  });
  return rows;
}

function setPlayerOpen(open) {
  libraryBody?.classList.toggle("library-body--playing", open);
  mediaPlayer?.classList.toggle("hidden", !open);
}

export function playMedia(item, username) {
  libraryState.playingUrl = item.url;
  if (playerTitle) playerTitle.textContent = `@${username} · ${item.filename}`;
  if (playerMeta) playerMeta.textContent = mediaItemMeta(item);
  setPlayerOpen(true);
  const targetUrl = new URL(item.url, window.location.origin).href;
  if (mediaPlayerVideo && mediaPlayerVideo.src !== targetUrl) {
    mediaPlayerVideo.src = item.url;
  }
  mediaPlayerVideo?.play().catch(() => {});
  highlightActiveRow();
}

export function closePlayer() {
  mediaPlayerVideo?.pause();
  mediaPlayerVideo?.removeAttribute("src");
  mediaPlayerVideo?.load();
  libraryState.playingUrl = null;
  setPlayerOpen(false);
  highlightActiveRow();
  maybeApplyPendingMedia();
}

function highlightActiveRow() {
  mediaLibrary?.querySelectorAll(".media-table-row").forEach((row) => {
    row.classList.toggle("is-active", row.dataset.url === libraryState.playingUrl);
  });
}

function createMediaTableRow(item, username, { showUser = true } = {}) {
  const row = document.createElement("div");
  row.className = "media-table-row";
  row.dataset.url = item.url;
  row.dataset.username = username;
  row.setAttribute("role", "button");
  row.tabIndex = 0;

  const nameCell = document.createElement("span");
  nameCell.className = "media-cell media-cell--name";
  const name = document.createElement("span");
  name.className = "media-row-name";
  name.title = item.filename;
  const badges = [];
  if (item.in_progress) badges.push("recording");
  if (item.needs_convert) badges.push("needs convert");
  const badgeSuffix = badges.length ? ` [${badges.join(", ")}]` : "";
  name.textContent = `${item.filename}${badgeSuffix}`;
  nameCell.append(name);

  const userCell = document.createElement("span");
  userCell.className = "media-cell media-cell--user";
  userCell.textContent = showUser ? `@${username}` : "";

  const sizeCell = document.createElement("span");
  sizeCell.className = "media-cell media-cell--size";
  sizeCell.textContent = formatBytes(item.size);

  const dateCell = document.createElement("span");
  dateCell.className = "media-cell media-cell--date";
  dateCell.textContent = formatTimestamp(item.modified_at);

  const actionsCell = document.createElement("span");
  actionsCell.className = "media-cell media-cell--actions";

  const playBtn = document.createElement("button");
  playBtn.type = "button";
  playBtn.className = "btn btn-ghost btn-small";
  playBtn.textContent = "Play";
  playBtn.addEventListener("click", (event) => {
    event.stopPropagation();
    playMedia(item, username);
  });

  const download = document.createElement("a");
  download.className = "btn btn-ghost btn-small";
  download.href = item.url;
  download.download = item.filename;
  download.textContent = "Save";
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
      if (libraryState.playingUrl === item.url) closePlayer();
      await refreshMedia({ force: true });
    } catch (error) {
      showToast(error.message);
    }
  });

  actionsCell.append(playBtn, download, deleteBtn);
  row.append(nameCell, userCell, sizeCell, dateCell, actionsCell);

  const activate = () => playMedia(item, username);
  row.addEventListener("click", (event) => {
    if (event.target.closest("button, a")) return;
    activate();
  });
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate();
    }
  });

  if (item.in_progress) row.classList.add("media-table-row--in-progress");
  if (item.needs_convert) row.classList.add("media-table-row--needs-convert");
  if (item.url === libraryState.playingUrl) row.classList.add("is-active");
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

function renderMediaTable(rows) {
  if (!mediaLibrary) return;

  const table = document.createElement("div");
  table.className = "media-table";

  const head = document.createElement("div");
  head.className = "media-table-head";
  head.innerHTML = `
    <span>Recording</span>
    <span>User</span>
    <span>Size</span>
    <span>Date</span>
    <span>Actions</span>
  `;
  table.append(head);

  const body = document.createElement("div");
  body.className = "media-table-body";

  const groupByUser = libraryState.sortMode === "user";
  let currentUser = null;

  if (groupByUser) {
    const groups = new Map();
    for (const entry of rows) {
      if (!groups.has(entry.username)) groups.set(entry.username, []);
      groups.get(entry.username).push(entry);
    }
    for (const [username, userRows] of groups) {
      const label = document.createElement("div");
      label.className = "media-group-label";
      label.textContent = `@${username} · ${userRows.length} recording${userRows.length === 1 ? "" : "s"} · ${formatBytes(sumMediaSize(userRows.map((entry) => entry.item)))}`;
      body.append(label);
      for (const { item } of userRows) {
        body.append(createMediaTableRow(item, username, { showUser: false }));
      }
    }
  } else {
    for (const { item, username } of rows) {
      body.append(createMediaTableRow(item, username, { showUser: true }));
    }
  }

  table.append(body);
  mediaLibrary.replaceChildren(table);
}

export function renderMedia(media) {
  setLatestMedia(media || {});
  const query = mediaSearch?.value || "";
  const filtered = filterMedia(latestMedia, query);

  updateLibrarySummary(filtered);

  const usernames = Object.keys(filtered);
  if (!usernames.length) {
    if (!isAnyMediaPlaying() && mediaLibrary) {
      mediaLibrary.innerHTML = query
        ? '<p class="empty library-empty">No recordings match your search.</p>'
        : '<p class="empty library-empty">No recordings yet.</p>';
    }
    return;
  }

  const rows = flattenAndSortMedia(filtered);
  renderMediaTable(rows);
}

export function maybeApplyPendingMedia() {
  if (pendingMedia && !shouldDeferMediaRender()) {
    const media = pendingMedia;
    setPendingMedia(null);
    renderMedia(media);
  }
}

export function applyMediaUpdate(media, { force = false } = {}) {
  if (!force && shouldDeferMediaRender()) {
    setPendingMedia(media);
    setLatestMedia(media || {});
    updateLibrarySummary(filterMedia(latestMedia, mediaSearch?.value || ""));
    return false;
  }
  setPendingMedia(null);
  renderMedia(media);
  return true;
}

export function updateConvertJobButton(job) {
  const btn = document.getElementById("convert-pending-btn");
  if (!btn || !job?.running) return;
  const progress = job.current_progress?.percent;
  const fileIndex = job.total ? Math.min(job.total, job.completed + 1) : null;
  const batchLabel = job.total ? ` · file ${fileIndex}/${job.total}` : "";
  if (progress != null) {
    btn.textContent = `Converting FLV… ${progress}%${batchLabel}`;
  } else {
    btn.textContent = `Converting FLV…${batchLabel}`;
  }
}

export function syncConvertJobUi(job) {
  const btn = document.getElementById("convert-pending-btn");
  const badge = document.getElementById("convert-pending-count");
  if (!btn) return;
  if (job?.running) {
    btn.disabled = true;
    updateConvertJobButton(job);
    return;
  }
  btn.textContent = "Convert leftover FLV";
}

export async function refreshPendingConvertCount(jobFromStatus = null) {
  const btn = document.getElementById("convert-pending-btn");
  const badge = document.getElementById("convert-pending-count");
  if (!btn) return;
  if (jobFromStatus?.running) {
    syncConvertJobUi(jobFromStatus);
    return;
  }
  try {
    const payload = await api("/api/media/pending-convert");
    const count = payload.count || 0;
    const job = payload.job;
    const running = Boolean(job?.running);
    btn.disabled = count === 0 || running;
    if (running) {
      updateConvertJobButton(job);
    } else {
      btn.textContent = "Convert leftover FLV";
    }
    if (badge) {
      if (count > 0 && !running) {
        badge.textContent = String(count);
        badge.classList.remove("hidden");
      } else {
        badge.classList.add("hidden");
      }
    }
  } catch {
    btn.disabled = true;
  }
}

export async function refreshMedia({ force = false } = {}) {
  const media = await api("/api/media");
  applyMediaUpdate(media, { force });
  await refreshPendingConvertCount();
}

export function initMediaInteractions() {
  document.getElementById("convert-pending-btn")?.addEventListener("click", async () => {
    try {
      const pending = await api("/api/media/pending-convert");
      const count = pending.count || 0;
      if (!count) {
        showToast("No leftover FLV files to convert");
        return;
      }
      if (!confirm(`Convert ${count} leftover FLV recording${count === 1 ? "" : "s"}?`)) {
        return;
      }
      await api("/api/media/convert-pending", { method: "POST" });
      showToast("Conversion started - check logs for progress");
      await refreshPendingConvertCount();
      const poll = setInterval(async () => {
        const status = await api("/api/media/pending-convert");
        await refreshPendingConvertCount();
        if (!status.job?.running) {
          clearInterval(poll);
          await refreshMedia({ force: true });
          const failed = status.job?.failed || 0;
          const completed = status.job?.completed || 0;
          showToast(`Convert finished: ${completed} ok, ${failed} failed`);
        }
      }, 3000);
    } catch (error) {
      showToast(error.message);
    }
  });

  document.getElementById("refresh-media-btn")?.addEventListener("click", async () => {
    try {
      await refreshMedia({ force: true });
      showToast("Media refreshed");
    } catch (error) {
      showToast(error.message);
    }
  });

  mediaSearch?.addEventListener("input", () => {
    renderMedia(latestMedia);
  });

  document.getElementById("library-sort")?.addEventListener("change", (event) => {
    saveLibrarySortMode(event.target.value);
    renderMedia(latestMedia);
  });

  document.getElementById("player-close")?.addEventListener("click", closePlayer);
  mediaPlayerVideo?.addEventListener("pause", maybeApplyPendingMedia);
  mediaPlayerVideo?.addEventListener("ended", maybeApplyPendingMedia);

  mediaPlayer?.addEventListener(
    "wheel",
    (event) => {
      event.stopPropagation();
    },
    { passive: true },
  );
}
