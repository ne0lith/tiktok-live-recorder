export const INITIAL_VISIBLE = 8;
export const LOAD_MORE_STEP = 20;
export const STATUS_ROW_LIMIT = 80;
export const API_TIMEOUT_MS = 12000;
export const LOG_REFRESH_MS = 3000;

export const STORAGE_VIEW_KEY = "ttlr_library_view";
export const STORAGE_SORT_KEY = "ttlr_library_sort";

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
export let statusRowLimit = STATUS_ROW_LIMIT;

export const libraryState = {
  expandedUsers: new Set(),
  visibleCounts: new Map(),
  playingUrl: null,
  viewMode: "by-user",
  sortMode: "newest",
  recentVisibleCount: null,
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

export function expandStatusRowLimit(count) {
  statusRowLimit = count;
}
