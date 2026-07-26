import { api, showToast } from "./api.js";
import { basename, formatBytes, formatTimestamp, usernamesMatch } from "./format.js";
import { updateSegmentedControl } from "./segmented.js";
import {
  INITIAL_VISIBLE,
  LOAD_MORE_STEP,
  STORAGE_SORT_KEY,
  STORAGE_VIEW_KEY,
  latestMedia,
  libraryState,
  pendingMedia,
  selectedProfile,
  setLatestMedia,
  setPendingMedia,
} from "./state.js";

const mediaLibrary = document.getElementById("media-library");
const librarySummary = document.getElementById("library-summary");
const mediaSearch = document.getElementById("media-search");
const mediaPlayer = document.getElementById("media-player");
const mediaPlayerVideo = document.getElementById("media-player-video");
const playerTitle = document.getElementById("player-title");
const playerMeta = document.getElementById("player-meta");

export function loadLibraryPreferences() {
  const savedView = localStorage.getItem(STORAGE_VIEW_KEY);
  if (savedView === "by-user" || savedView === "recent") {
    libraryState.viewMode = savedView;
  }
  const savedSort = localStorage.getItem(STORAGE_SORT_KEY);
  if (savedSort) libraryState.sortMode = savedSort;
  const sortSelect = document.getElementById("library-sort");
  if (sortSelect) sortSelect.value = libraryState.sortMode;
}

export function saveLibraryViewMode(mode) {
  libraryState.viewMode = mode;
  localStorage.setItem(STORAGE_VIEW_KEY, mode);
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
  const focusSuffix = selectedProfile ? ` · focused @${selectedProfile}` : "";
  librarySummary.textContent = `${fileCount} recording${fileCount === 1 ? "" : "s"} · ${usernames.length} user${usernames.length === 1 ? "" : "s"} · ${formatBytes(totalSize)}${focusSuffix}`;
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

function getRecentVisibleCount(total) {
  if (libraryState.recentVisibleCount == null) {
    libraryState.recentVisibleCount = Math.min(INITIAL_VISIBLE, total);
  }
  return Math.min(libraryState.recentVisibleCount, total);
}

export function syncLibraryViewButtons() {
  const byUser = document.getElementById("library-view-by-user");
  const recent = document.getElementById("library-view-recent");
  const toggle = document.getElementById("library-view-toggle");
  if (!byUser || !recent) return;
  byUser.classList.toggle("is-active", libraryState.viewMode === "by-user");
  recent.classList.toggle("is-active", libraryState.viewMode === "recent");
  updateSegmentedControl(toggle);
}

function applyLibraryViewToggle() {
  document.getElementById("library-view-toggle")?.classList.remove("hidden");
}

export function setLibraryViewMode(mode) {
  if (libraryState.viewMode === mode) return;
  saveLibraryViewMode(mode);
  libraryState.recentVisibleCount = null;
  syncLibraryViewButtons();
  renderMedia(latestMedia);
}

function getVisibleCount(username, total) {
  if (!libraryState.visibleCounts.has(username)) {
    libraryState.visibleCounts.set(username, Math.min(INITIAL_VISIBLE, total));
  }
  return Math.min(libraryState.visibleCounts.get(username), total);
}

function setExpanded(username, expanded) {
  if (expanded) libraryState.expandedUsers.add(username);
  else libraryState.expandedUsers.delete(username);
}

export function playMedia(item, username) {
  libraryState.playingUrl = item.url;
  setExpanded(username, true);
  if (playerTitle) playerTitle.textContent = `@${username} · ${item.filename}`;
  if (playerMeta) playerMeta.textContent = mediaItemMeta(item);
  mediaPlayer?.classList.remove("hidden");
  mediaPlayer?.classList.add("is-sticky");
  const targetUrl = new URL(item.url, window.location.origin).href;
  if (mediaPlayerVideo && mediaPlayerVideo.src !== targetUrl) {
    mediaPlayerVideo.src = item.url;
  }
  mediaPlayerVideo?.play().catch(() => {});
  mediaLibrary
    ?.querySelector(`.user-section[data-username="${CSS.escape(username)}"]`)
    ?.classList.add("expanded");
  mediaLibrary
    ?.querySelector(`.media-row[data-url="${CSS.escape(item.url)}"]`)
    ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  highlightActiveRow();
}

export function closePlayer() {
  mediaPlayerVideo?.pause();
  mediaPlayerVideo?.removeAttribute("src");
  mediaPlayerVideo?.load();
  libraryState.playingUrl = null;
  mediaPlayer?.classList.add("hidden");
  mediaPlayer?.classList.remove("is-sticky");
  highlightActiveRow();
}

function highlightActiveRow() {
  mediaLibrary?.querySelectorAll(".media-row").forEach((row) => {
    row.classList.toggle("is-active", row.dataset.url === libraryState.playingUrl);
  });
}

function createMediaRow(item, username, { showUsername = false } = {}) {
  const row = document.createElement("div");
  row.className = "media-row";
  row.dataset.url = item.url;
  row.dataset.username = username;

  const main = document.createElement("button");
  main.type = "button";
  main.className = "media-row-main";

  if (!item.in_progress) {
    const thumb = document.createElement("video");
    thumb.className = "media-thumb";
    thumb.muted = true;
    thumb.playsInline = true;
    thumb.preload = "metadata";
    thumb.src = item.url;
    thumb.addEventListener("loadeddata", () => {
      try {
        thumb.currentTime = 0.1;
      } catch {
        // ignore seek errors on short files
      }
    });
    main.append(thumb);
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
  const inProgressBadge = item.in_progress ? " [recording]" : "";
  const needsConvertBadge = item.needs_convert ? " [needs convert]" : "";
  name.textContent = showUsername
    ? `@${username} · ${item.filename}${inProgressBadge}${needsConvertBadge}`
    : `${item.filename}${inProgressBadge}${needsConvertBadge}`;

  const meta = document.createElement("span");
  meta.className = "media-row-meta";
  meta.textContent = mediaItemMeta(item);

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
  let section = mediaLibrary?.querySelector(
    `.user-section[data-username="${CSS.escape(username)}"]`,
  );
  if (!section && mediaLibrary) {
    section = document.createElement("section");
    section.className = "user-section";
    section.dataset.username = username;
    section.innerHTML = `
      <button class="user-section-toggle" type="button">
        <span class="user-section-title"></span>
        <span class="user-section-count"></span>
        <span class="user-section-chevron" aria-hidden="true">'</span>
      </button>
      <div class="user-section-storage hidden" aria-hidden="true">
        <span class="user-section-storage-bar"></span>
      </div>
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
      libraryState.visibleCounts.set(username, Math.min(current + LOAD_MORE_STEP, items.length));
      renderMedia(latestMedia);
    });
    mediaLibrary.append(section);
  }

  const expanded =
    libraryState.expandedUsers.has(username) ||
    (selectedProfile && usernamesMatch(username, selectedProfile));
  section?.classList.toggle("expanded", expanded);
  section?.classList.toggle(
    "user-section--focused",
    selectedProfile && usernamesMatch(username, selectedProfile),
  );
  const title = section?.querySelector(".user-section-title");
  if (title) {
    title.textContent = `@${username}`;
    title.classList.add("profile-link");
    title.dataset.profile = username;
    title.classList.toggle("is-active", usernamesMatch(username, selectedProfile));
    if (!title.dataset.profileBound) {
      title.dataset.profileBound = "true";
      title.addEventListener("click", (event) => {
        event.stopPropagation();
        import("./status.js").then((m) => m.setSelectedProfile(username));
      });
    }
  }
  section?.querySelector(".user-section-count")?.replaceChildren();
  const countEl = section?.querySelector(".user-section-count");
  if (countEl) {
    const totalBytes = sumMediaSize(items);
    countEl.textContent = `${items.length} recording${items.length === 1 ? "" : "s"} · ${formatBytes(totalBytes)}`;
  }

  const storageWrap = section?.querySelector(".user-section-storage");
  const storageBar = section?.querySelector(".user-section-storage-bar");
  const libraryTotal = sumMediaSize(Object.values(latestMedia).flat());
  if (storageWrap && storageBar && libraryTotal > 0) {
    const share = sumMediaSize(items) / libraryTotal;
    storageWrap.classList.remove("hidden");
    storageWrap.setAttribute("aria-hidden", "false");
    storageBar.style.width = `${Math.max(4, Math.round(share * 100))}%`;
    storageWrap.title = `${Math.round(share * 100)}% of library storage`;
  } else {
    storageWrap?.classList.add("hidden");
  }

  const visibleCount = getVisibleCount(username, items.length);
  const list = section?.querySelector(".media-list");
  list?.replaceChildren();
  for (const item of items.slice(0, visibleCount)) {
    const row = createMediaRow(item, username);
    if (item.url === libraryState.playingUrl) row.classList.add("is-active");
    list?.append(row);
  }

  const footer = section?.querySelector(".user-section-footer");
  const showMore = section?.querySelector(".show-more");
  if (visibleCount < items.length) {
    footer?.classList.remove("hidden");
    if (showMore) showMore.textContent = `Show ${items.length - visibleCount} more`;
  } else {
    footer?.classList.add("hidden");
  }
}

function renderRecentList(media) {
  const rows = flattenAndSortMedia(media);
  const visibleCount = getRecentVisibleCount(rows.length);

  mediaLibrary?.querySelectorAll(".user-section").forEach((section) => section.remove());

  let section = mediaLibrary?.querySelector(".recent-section");
  if (!section && mediaLibrary) {
    section = document.createElement("section");
    section.className = "recent-section";
    section.innerHTML = `
      <div class="recent-section-head">
        <h3 class="recent-section-title">All recordings</h3>
        <span class="recent-section-count"></span>
      </div>
      <div class="media-list"></div>
      <div class="recent-section-footer hidden">
        <button class="btn btn-ghost btn-small show-more" type="button"></button>
      </div>
    `;
    section.querySelector(".show-more").addEventListener("click", () => {
      const current = getRecentVisibleCount(rows.length);
      libraryState.recentVisibleCount = Math.min(current + LOAD_MORE_STEP, rows.length);
      renderMedia(latestMedia);
    });
    mediaLibrary.append(section);
  }

  section?.querySelector(".recent-section-count")?.replaceChildren();
  const countNode = section?.querySelector(".recent-section-count");
  if (countNode) {
    countNode.textContent = `${rows.length} recording${rows.length === 1 ? "" : "s"} · ${formatBytes(sumMediaSize(rows.map((entry) => entry.item)))}`;
  }

  const list = section?.querySelector(".media-list");
  list?.replaceChildren();
  for (const { item, username } of rows.slice(0, visibleCount)) {
    const row = createMediaRow(item, username, { showUsername: true });
    if (item.url === libraryState.playingUrl) row.classList.add("is-active");
    list?.append(row);
  }

  const footer = section?.querySelector(".recent-section-footer");
  const showMore = section?.querySelector(".show-more");
  if (visibleCount < rows.length) {
    footer?.classList.remove("hidden");
    if (showMore) showMore.textContent = `Show ${rows.length - visibleCount} more`;
  } else {
    footer?.classList.add("hidden");
  }
}

export function renderMedia(media) {
  setLatestMedia(media || {});
  const query = mediaSearch?.value || "";
  const filtered = filterMedia(latestMedia, query);
  if (mediaSearch) {
    mediaSearch.placeholder = "Search by username or filename…";
  }

  const usernames = Object.keys(filtered).sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: "base" }),
  );

  updateLibrarySummary(filtered);

  if (!usernames.length) {
    if (!isAnyMediaPlaying() && mediaLibrary) {
      mediaLibrary.innerHTML = query
        ? '<p class="empty">No recordings match your search.</p>'
        : '<p class="empty">No recordings yet.</p>';
    }
    applyLibraryViewToggle();
    return;
  }

  mediaLibrary?.querySelector(".empty")?.remove();
  applyLibraryViewToggle();

  if (libraryState.viewMode === "recent") {
    renderRecentList(filtered);
    return;
  }

  mediaLibrary?.querySelector(".recent-section")?.remove();
  const seenUsers = new Set();

  for (const username of usernames) {
    seenUsers.add(username);
    renderUserSection(username, filtered[username]);
  }

  mediaLibrary?.querySelectorAll(".user-section").forEach((section) => {
    if (!seenUsers.has(section.dataset.username)) section.remove();
  });

  if (usernames.length === 1 && !query) {
    setExpanded(usernames[0], true);
    mediaLibrary
      ?.querySelector(`.user-section[data-username="${CSS.escape(usernames[0])}"]`)
      ?.classList.add("expanded");
  }
}

export function maybeApplyPendingMedia() {
  if (pendingMedia && !isAnyMediaPlaying()) {
    const media = pendingMedia;
    setPendingMedia(null);
    renderMedia(media);
  }
}

export async function refreshPendingConvertCount() {
  const btn = document.getElementById("convert-pending-btn");
  const badge = document.getElementById("convert-pending-count");
  if (!btn) return;
  try {
    const payload = await api("/api/media/pending-convert");
    const count = payload.count || 0;
    const running = Boolean(payload.job?.running);
    btn.disabled = count === 0 || running;
    btn.textContent = running ? "Converting FLV…" : "Convert leftover FLV";
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
  if (!force && isAnyMediaPlaying()) {
    setPendingMedia(media);
    return;
  }
  setPendingMedia(null);
  renderMedia(media);
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
    libraryState.recentVisibleCount = null;
    renderMedia(latestMedia);
  });

  document.getElementById("library-view-by-user")?.addEventListener("click", () => {
    setLibraryViewMode("by-user");
  });

  document.getElementById("library-view-recent")?.addEventListener("click", () => {
    setLibraryViewMode("recent");
  });

  document.getElementById("library-sort")?.addEventListener("change", (event) => {
    saveLibrarySortMode(event.target.value);
    libraryState.recentVisibleCount = null;
    renderMedia(latestMedia);
  });

  document.getElementById("player-close")?.addEventListener("click", closePlayer);
  mediaPlayerVideo?.addEventListener("pause", maybeApplyPendingMedia);
  mediaPlayerVideo?.addEventListener("ended", maybeApplyPendingMedia);
}
