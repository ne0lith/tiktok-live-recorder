export const API_TIMEOUT_MS = 12000;
export const LOG_REFRESH_MS = 3000;

export const STORAGE_SORT_KEY = "ttlr_library_sort";
export const STORAGE_SHOW_LEGACY_KEY = "ttlr_library_show_legacy";
export const STORAGE_HIDDEN_USERS_KEY = "ttlr_library_hidden_users";
export const STORAGE_HIDE_PAUSED_KEY = "ttlr_hide_paused";
export const STORAGE_STATUS_SORT_KEY = "ttlr_status_sort";
export const STORAGE_ACTIVITY_HIDDEN_KINDS_KEY = "ttlr_activity_hidden_kinds";

export const STATE_SORT_ORDER = {
  recording: 0,
  converting: 0,
  convert_queued: 0,
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
export let statusSortMode = "state";
export let hidePausedUsers = false;
export let activityHiddenKinds = new Set();

export const libraryState = {
  playingUrl: null,
  playingUsername: null,
  playingItem: null,
  sortMode: "newest",
  showLegacy: false,
  /** @type {Set<string>} normalized usernames excluded from library results */
  hiddenUsers: new Set(),
  /** @type {Map<string, {username: string, filename: string, source: string, url: string}>} */
  selectedMedia: new Map(),
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

export function setStatusSortMode(mode) {
  statusSortMode = mode;
}

export function setHidePausedUsers(value) {
  hidePausedUsers = Boolean(value);
}

export function setActivityHiddenKinds(kinds) {
  activityHiddenKinds = kinds instanceof Set ? kinds : new Set(kinds || []);
}
