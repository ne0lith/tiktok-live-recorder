import { api, showToast } from "./api.js";
import { formatBytes, formatTimestamp, usernamesMatch } from "./format.js";
import { createMediaThumb, observeMediaThumbs } from "./media-thumbs.js";
import {
  STORAGE_SHOW_LEGACY_KEY,
  STORAGE_SORT_KEY,
  latestMedia,
  libraryState,
  pendingMedia,
  selectedProfile,
  setLatestMedia,
  setPendingMedia,
} from "./state.js";

const libraryBody = document.getElementById("library-body");
const mediaLibrary = document.getElementById("media-library");
const librarySummary = document.getElementById("library-summary");
const mediaSearch = document.getElementById("media-search");
const mediaPlayer = document.getElementById("media-player");
const mediaPlayerVideo = document.getElementById("media-player-video");
const playerUsername = document.getElementById("player-username");
const playerFilename = document.getElementById("player-filename");
const playerMeta = document.getElementById("player-meta");

export function loadLibraryPreferences() {
  const savedSort = localStorage.getItem(STORAGE_SORT_KEY);
  if (savedSort) libraryState.sortMode = savedSort;
  libraryState.showLegacy = localStorage.getItem(STORAGE_SHOW_LEGACY_KEY) === "1";
  const sortSelect = document.getElementById("library-sort");
  if (sortSelect) sortSelect.value = libraryState.sortMode;
  syncLibraryShowLegacyToggle();
}

export function saveLibrarySortMode(mode) {
  libraryState.sortMode = mode;
  localStorage.setItem(STORAGE_SORT_KEY, mode);
}

export function saveShowLegacyPreference(show) {
  libraryState.showLegacy = Boolean(show);
  localStorage.setItem(STORAGE_SHOW_LEGACY_KEY, show ? "1" : "0");
  syncLibraryShowLegacyToggle();
}

export function syncLibraryShowLegacyToggle() {
  const toggle = document.getElementById("library-show-legacy");
  if (toggle) toggle.checked = libraryState.showLegacy;
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

function stripLegacyItems(media) {
  const filtered = {};
  for (const [username, items] of Object.entries(media || {})) {
    const visible = items.filter((item) => item.source !== "legacy");
    if (visible.length) filtered[username] = visible;
  }
  return filtered;
}

function applyLibraryFilters(media, query) {
  let filtered = filterMedia(media, query);
  if (!libraryState.showLegacy) {
    filtered = stripLegacyItems(filtered);
  }
  if (!selectedProfile) return filtered;

  const scoped = {};
  for (const [username, items] of Object.entries(filtered)) {
    if (usernamesMatch(username, selectedProfile)) {
      scoped[username] = items;
    }
  }
  return scoped;
}

function updateLibrarySummary(media) {
  const source = media || latestMedia || {};
  const usernames = Object.keys(source);
  const fileCount = usernames.reduce((total, username) => total + source[username].length, 0);
  const totalSize = usernames.reduce(
    (total, username) => total + sumMediaSize(source[username]),
    0,
  );
  if (!librarySummary) return;
  const focusSuffix = selectedProfile ? ` · @${selectedProfile}` : "";
  const legacySuffix = libraryState.showLegacy ? "" : " · legacy hidden";
  librarySummary.textContent = `${fileCount} recording${fileCount === 1 ? "" : "s"} · ${usernames.length} user${usernames.length === 1 ? "" : "s"} · ${formatBytes(totalSize)}${focusSuffix}${legacySuffix}`;
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
  if (playerUsername) playerUsername.textContent = `@${username}`;
  if (playerFilename) playerFilename.textContent = item.filename;
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
  mediaLibrary?.querySelectorAll(".media-row").forEach((row) => {
    row.classList.toggle("is-active", row.dataset.url === libraryState.playingUrl);
  });
}

function createMediaRow(item, username) {
  const row = document.createElement("article");
  row.className = "media-row";
  row.dataset.url = item.url;
  row.dataset.username = username;

  const main = document.createElement("button");
  main.type = "button";
  main.className = "media-row-main";

  if (!item.in_progress) {
    main.append(createMediaThumb(item));
  } else {
    const thumb = document.createElement("span");
    thumb.className = "media-thumb media-thumb--live";
    thumb.textContent = "●";
    main.append(thumb);
  }

  const body = document.createElement("span");
  body.className = "media-row-body";
  const name = document.createElement("span");
  name.className = "media-row-name";
  name.title = item.filename;
  name.textContent = item.filename;

  const meta = document.createElement("span");
  meta.className = "media-row-meta";
  meta.textContent = `@${username} · ${mediaItemMeta(item)}`;

  const play = document.createElement("span");
  play.className = "media-row-play";
  play.textContent = "Play";

  body.append(name, meta);
  main.append(body, play);
  main.addEventListener("click", () => playMedia(item, username));

  const actions = document.createElement("div");
  actions.className = "media-row-actions";

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

  actions.append(download, deleteBtn);
  row.append(main, actions);

  if (item.in_progress) row.classList.add("media-row--in-progress");
  if (item.needs_convert) row.classList.add("media-row--needs-convert");
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

function renderMediaList(rows) {
  if (!mediaLibrary) return;

  const list = document.createElement("div");
  list.className = "media-list";

  if (libraryState.sortMode === "user") {
    const groups = new Map();
    for (const entry of rows) {
      if (!groups.has(entry.username)) groups.set(entry.username, []);
      groups.get(entry.username).push(entry);
    }
    for (const [username, userRows] of groups) {
      const label = document.createElement("p");
      label.className = "media-section-label";
      label.textContent = `@${username} · ${userRows.length} recording${userRows.length === 1 ? "" : "s"} · ${formatBytes(sumMediaSize(userRows.map((entry) => entry.item)))}`;
      list.append(label);
      for (const { item } of userRows) {
        list.append(createMediaRow(item, username));
      }
    }
  } else {
    for (const { item, username } of rows) {
      list.append(createMediaRow(item, username));
    }
  }

  mediaLibrary.replaceChildren(list);
  observeMediaThumbs(list);
}

export function renderMedia(media) {
  setLatestMedia(media || {});
  const query = mediaSearch?.value || "";
  const filtered = applyLibraryFilters(latestMedia, query);

  updateLibrarySummary(filtered);

  const usernames = Object.keys(filtered);
  if (!usernames.length) {
    if (!isAnyMediaPlaying() && mediaLibrary) {
      const emptyMessage = selectedProfile
        ? `No recordings for @${selectedProfile}${query ? " matching your search." : "."}`
        : query
          ? "No recordings match your search."
          : !libraryState.showLegacy && Object.keys(latestMedia || {}).length
            ? "No recordings visible (legacy hidden)."
            : "No recordings yet.";
      mediaLibrary.innerHTML = `<p class="empty library-empty">${emptyMessage}</p>`;
    }
    return;
  }

  const rows = flattenAndSortMedia(filtered);
  renderMediaList(rows);
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
    updateLibrarySummary(applyLibraryFilters(latestMedia, mediaSearch?.value || ""));
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
