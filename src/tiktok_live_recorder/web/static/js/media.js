import { api, showToast } from "./api.js";
import { formatBytes, formatTimestamp, usernamesMatch } from "./format.js";
import { createMediaThumb, observeMediaThumbs } from "./media-thumbs.js";
import {
  STORAGE_SHOW_LEGACY_KEY,
  STORAGE_SORT_KEY,
  latestMedia,
  latestStatus,
  libraryState,
  pendingMedia,
  selectedProfile,
  setLatestMedia,
  setPendingMedia,
} from "./state.js";
import {
  buildUserActionButtons,
  profileLinkMarkup,
  runUserAction,
} from "./user-actions.js";

const libraryBody = document.getElementById("library-body");
const mediaLibrary = document.getElementById("media-library");
const librarySummary = document.getElementById("library-summary");
const mediaSearch = document.getElementById("media-search");
const mediaPlayer = document.getElementById("media-player");
const mediaPlayerVideo = document.getElementById("media-player-video");
const playerUsername = document.getElementById("player-username");
const playerFilename = document.getElementById("player-filename");
const playerMeta = document.getElementById("player-meta");
const playerActions = document.getElementById("player-actions");
const playerFileActions = document.getElementById("player-file-actions");
const playerRepairBtn = document.getElementById("player-repair");

function repairApiPath(username, item) {
  const encodedUser = encodeURIComponent(username);
  const encodedFile = encodeURIComponent(item.filename);
  if (item.source === "legacy") {
    return `/api/media/${encodedUser}/legacy/${encodedFile}/repair`;
  }
  return `/api/media/${encodedUser}/${encodedFile}/repair`;
}

function itemHasThumbnail(item) {
  if (!item?.thumb_url) return Promise.resolve(false);
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(true);
    img.onerror = () => resolve(false);
    img.src = `${item.thumb_url}?probe=${Date.now()}`;
  });
}

async function updatePlayerRepairButton(item) {
  if (!playerRepairBtn) return;
  if (!item || item.in_progress) {
    playerRepairBtn.classList.add("hidden");
    playerRepairBtn.disabled = false;
    return;
  }
  const hasThumb = await itemHasThumbnail(item);
  const show = !hasThumb;
  playerRepairBtn.classList.toggle("hidden", !show);
  if (show) {
    playerRepairBtn.disabled = false;
    playerRepairBtn.textContent = item.needs_convert ? "Convert" : "Fix video";
  }
}

function hidePlayerRepairButton() {
  playerRepairBtn?.classList.add("hidden");
  if (playerRepairBtn) playerRepairBtn.disabled = false;
}

export function syncPlayerRepairFromStatus(status) {
  if (!playerRepairBtn || !libraryState.playingItem) return;
  const item = libraryState.playingItem;
  const jobs = status?.media_jobs || [];
  const job = jobs.find(
    (entry) => entry.filename === item.filename || (item.path && entry.path === item.path),
  );
  if (!job) return;
  playerRepairBtn.classList.remove("hidden");
  playerRepairBtn.disabled = true;
  if (job.status === "converting") {
    playerRepairBtn.textContent = item.needs_convert ? "Converting…" : "Fixing…";
  } else {
    playerRepairBtn.textContent =
      job.queue_position && job.queue_position > 1
        ? `Queued (#${job.queue_position})`
        : "Queued…";
  }
}

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
  if (item.needs_convert) statusBits.push("needs convert");
  const statusSuffix = statusBits.length ? ` · ${statusBits.join(", ")}` : "";
  return `${formatBytes(item.size)} · ${formatTimestamp(item.modified_at)}${statusSuffix}${
    item.source === "legacy" ? " · legacy" : ""
  }`;
}

function sumMediaSize(items) {
  return items.reduce((total, item) => total + (item.size || 0), 0);
}

export function mediaItemsForUser(username, media = latestMedia) {
  for (const [key, items] of Object.entries(media || {})) {
    if (usernamesMatch(key, username)) return items;
  }
  return [];
}

export function sumLibraryBytesForUser(username, media = latestMedia) {
  return sumMediaSize(
    mediaItemsForUser(username, media).filter(
      (item) => !item.in_progress && !item.needs_convert,
    ),
  );
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
  playerFileActions?.classList.toggle("hidden", !open);
}

function renderPlayerHeader(username) {
  if (!playerUsername) return;
  if (!username || username.toLowerCase() === "unknown") {
    playerUsername.textContent = `@${username}`;
    return;
  }
  const active = usernamesMatch(username, selectedProfile);
  playerUsername.innerHTML = profileLinkMarkup(username, { active });
}

function renderPlayerActions() {
  if (!playerActions) return;
  const username = libraryState.playingUsername;
  if (!username) {
    playerActions.classList.add("hidden");
    playerActions.innerHTML = "";
    return;
  }
  const markup = buildUserActionButtons(username, latestStatus, null, { context: "player" });
  if (!markup) {
    playerActions.classList.add("hidden");
    playerActions.innerHTML = "";
    return;
  }
  playerActions.innerHTML = markup;
  playerActions.classList.remove("hidden");
}

export function playMedia(item, username) {
  libraryState.playingUrl = item.url;
  libraryState.playingUsername = username;
  libraryState.playingItem = item;
  renderPlayerHeader(username);
  if (playerFilename) playerFilename.textContent = item.filename;
  if (playerMeta) playerMeta.textContent = mediaItemMeta(item);
  renderPlayerActions();
  setPlayerOpen(true);
  void updatePlayerRepairButton(item);
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
  libraryState.playingUsername = null;
  libraryState.playingItem = null;
  hidePlayerRepairButton();
  if (playerActions) {
    playerActions.classList.add("hidden");
    playerActions.innerHTML = "";
  }
  setPlayerOpen(false);
  highlightActiveRow();
  maybeApplyPendingMedia();
}

function highlightActiveRow() {
  mediaLibrary?.querySelectorAll(".media-card").forEach((card) => {
    card.classList.toggle("is-active", card.dataset.url === libraryState.playingUrl);
  });
}

function createMediaCard(item, username) {
  const card = document.createElement("article");
  card.className = "media-card";
  card.dataset.url = item.url;
  card.dataset.username = username;

  const main = document.createElement("button");
  main.type = "button";
  main.className = "media-card-main";
  main.setAttribute("aria-label", `Play ${item.filename}`);

  const thumbWrap = document.createElement("span");
  thumbWrap.className = "media-card-thumb";
  thumbWrap.append(createMediaThumb(item));

  const body = document.createElement("span");
  body.className = "media-card-body";
  const name = document.createElement("span");
  name.className = "media-card-name";
  name.title = item.filename;
  name.textContent = item.filename;

  const meta = document.createElement("span");
  meta.className = "media-card-meta";
  if (username.toLowerCase() === "unknown") {
    meta.textContent = `@${username} · ${mediaItemMeta(item)}`;
  } else {
    const profileActive = usernamesMatch(username, selectedProfile);
    meta.innerHTML = `${profileLinkMarkup(username, { active: profileActive })}<span class="media-card-meta-sep"> · </span>${mediaItemMeta(item)}`;
    meta.querySelector("[data-profile]")?.addEventListener("click", async (event) => {
      event.stopPropagation();
      const { setSelectedProfile } = await import("./status.js");
      setSelectedProfile(username);
    });
  }

  body.append(name, meta);
  main.append(thumbWrap, body);
  main.addEventListener("click", () => playMedia(item, username));

  const actions = document.createElement("div");
  actions.className = "media-card-actions";

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
  card.append(main, actions);

  if (item.needs_convert) card.classList.add("media-card--needs-convert");
  if (item.url === libraryState.playingUrl) card.classList.add("is-active");
  return card;
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
        list.append(createMediaCard(item, username));
      }
    }
  } else {
    for (const { item, username } of rows) {
      list.append(createMediaCard(item, username));
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
    window.dispatchEvent(new CustomEvent("ttlr:media-updated"));
    return false;
  }
  setPendingMedia(null);
  renderMedia(media);
  window.dispatchEvent(new CustomEvent("ttlr:media-updated"));
  return true;
}

export async function refreshLeftoverFlvButton() {
  const btn = document.getElementById("move-leftover-btn");
  const badge = document.getElementById("move-leftover-count");
  if (!btn) return;
  try {
    const payload = await api("/api/media/leftover-flv");
    const count = payload.count || 0;
    if (count > 0) {
      btn.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = "Move leftover FLVs";
      if (badge) {
        badge.textContent = String(count);
        badge.classList.remove("hidden");
      }
    } else {
      btn.classList.add("hidden");
      btn.disabled = true;
      if (badge) {
        badge.classList.add("hidden");
      }
    }
  } catch {
    btn.classList.add("hidden");
    btn.disabled = true;
  }
}

export async function refreshMedia({ force = false } = {}) {
  const media = await api("/api/media");
  applyMediaUpdate(media, { force });
  await refreshLeftoverFlvButton();
}

export function initMediaInteractions() {
  document.getElementById("move-leftover-btn")?.addEventListener("click", async () => {
    const btn = document.getElementById("move-leftover-btn");
    try {
      const pending = await api("/api/media/leftover-flv");
      const count = pending.count || 0;
      if (!count) {
        showToast("No leftover FLV files to move");
        return;
      }
      if (!confirm(`Move ${count} leftover FLV recording${count === 1 ? "" : "s"} to to_fix/?`)) {
        return;
      }
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Moving…";
      }
      const result = await api("/api/media/move-leftover-flv", { method: "POST" });
      const moved = result.moved || 0;
      const failed = result.failed || 0;
      showToast(`Moved ${moved} file${moved === 1 ? "" : "s"}${failed ? `, ${failed} failed` : ""}`);
      await refreshMedia({ force: true });
    } catch (error) {
      showToast(error.message);
      await refreshLeftoverFlvButton();
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

  playerRepairBtn?.addEventListener("click", async () => {
    const item = libraryState.playingItem;
    const username = libraryState.playingUsername;
    if (!item || !username) return;
    const label = item.needs_convert ? "convert" : "repair";
    if (!confirm(`${label === "convert" ? "Convert" : "Fix"} ${item.filename}?`)) return;
    try {
      playerRepairBtn.disabled = true;
      playerRepairBtn.textContent = "Queued…";
      const result = await api(repairApiPath(username, item), { method: "POST" });
      const position = result.position;
      showToast(
        position > 1
          ? `Queued (position ${position})`
          : `${label === "convert" ? "Conversion" : "Repair"} queued`,
      );
    } catch (error) {
      showToast(error.message);
      playerRepairBtn.disabled = false;
      void updatePlayerRepairButton(item);
    }
  });

  document.getElementById("player-delete")?.addEventListener("click", async () => {
    const item = libraryState.playingItem;
    const username = libraryState.playingUsername;
    if (!item || !username) return;
    if (!confirm(`Delete ${item.filename}?`)) return;
    try {
      await deleteMediaItem(username, item);
      showToast(`Deleted ${item.filename}`);
      closePlayer();
      await refreshMedia({ force: true });
    } catch (error) {
      showToast(error.message);
    }
  });

  playerActions?.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    event.preventDefault();
    const { action, user } = button.dataset;
    await runUserAction(action, user, {
      onSuccess: async () => {
        const { refreshStatus } = await import("./status.js");
        await refreshStatus();
        renderPlayerActions();
      },
    });
  });

  const handleProfileClick = async (event) => {
    const profileButton = event.target.closest("button[data-profile]");
    if (!profileButton) return;
    event.stopPropagation();
    event.preventDefault();
    const { setSelectedProfile } = await import("./status.js");
    setSelectedProfile(profileButton.dataset.profile);
  };

  mediaPlayer?.addEventListener("click", handleProfileClick);

  window.addEventListener("ttlr:media-updated", () => {
    if (libraryState.playingUrl) {
      const items = mediaItemsForUser(libraryState.playingUsername || "");
      const stillThere = items.some((entry) => entry.url === libraryState.playingUrl);
      if (!stillThere) {
        closePlayer();
        return;
      }
    }
    const item = libraryState.playingItem;
    if (item) void updatePlayerRepairButton(item);
  });

  window.addEventListener("ttlr:status-updated", () => {
    if (libraryState.playingUsername) renderPlayerActions();
    if (latestStatus) syncPlayerRepairFromStatus(latestStatus);
  });

  window.addEventListener("ttlr:profile-changed", () => {
    if (libraryState.playingUsername) {
      renderPlayerHeader(libraryState.playingUsername);
    }
  });

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
