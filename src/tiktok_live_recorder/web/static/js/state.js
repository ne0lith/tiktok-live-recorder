export const API_TIMEOUT_MS = 12000;
export const LOG_REFRESH_MS = 3000;

export const STORAGE_SORT_KEY = "ttlr_library_sort";
export const STORAGE_SHOW_LEGACY_KEY = "ttlr_library_show_legacy";

export const STATE_SORT_ORDER = {
  recording: 0,
  converting: 0,
  stopping: 0,
  live: 1,
  starting: 1,
  error: 2,
  offline: 3,
  paused: 4,
  finished: 5,
};

export let latestStatus = null;
export let latestMedia = {};
export let pendingMedia = null;
export let selectedProfile = null;
export let statusFilter = "all";

export const libraryState = {
  playingUrl: null,
  sortMode: "newest",
  showLegacy: false,
};

export const logState = {
  timer: null,
  stickToBottom: true,
  lastText: "",
};

export function setLatestStatus(status) {
  latestStatus = status;
}

export function setLatestMedia(media) {
  latestMedia = media || {};
}

export function setPendingMedia(media) {
  pendingMedia = media;
}

export function setSelectedProfileValue(username) {
  selectedProfile = username;
}

export function setStatusFilter(filter) {
  statusFilter = filter;
}
