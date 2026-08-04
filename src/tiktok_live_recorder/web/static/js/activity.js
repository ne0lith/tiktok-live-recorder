import { formatTimestamp } from "./format.js";
import {
  STORAGE_ACTIVITY_HIDDEN_KINDS_KEY,
  activityHiddenKinds,
  setActivityHiddenKinds,
} from "./state.js";

const feed = document.getElementById("activity-feed");
const filtersEl = document.getElementById("activity-filters");

const KIND_LABELS = {
  poll: "Poll",
  recording: "Recording",
  telegram: "Telegram",
  media: "Media",
};

const FILTER_KINDS = Object.keys(KIND_LABELS);

let latestEvents = [];
let filtersBound = false;
let preferencesLoaded = false;

function isKindHidden(kind) {
  return activityHiddenKinds.has(kind);
}

function saveHiddenKinds() {
  localStorage.setItem(
    STORAGE_ACTIVITY_HIDDEN_KINDS_KEY,
    JSON.stringify([...activityHiddenKinds]),
  );
}

export function loadActivityPreferences() {
  if (preferencesLoaded) return;
  preferencesLoaded = true;
  try {
    const raw = localStorage.getItem(STORAGE_ACTIVITY_HIDDEN_KINDS_KEY);
    if (!raw) {
      setActivityHiddenKinds(new Set());
      return;
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      setActivityHiddenKinds(new Set());
      return;
    }
    setActivityHiddenKinds(
      new Set(parsed.filter((kind) => FILTER_KINDS.includes(kind))),
    );
  } catch {
    setActivityHiddenKinds(new Set());
  }
}

function toggleKindHidden(kind) {
  const next = new Set(activityHiddenKinds);
  if (next.has(kind)) next.delete(kind);
  else next.add(kind);
  setActivityHiddenKinds(next);
  saveHiddenKinds();
  renderActivityFilters();
  renderActivityFeed(latestEvents);
}

function renderActivityFilters() {
  if (!filtersEl) return;
  filtersEl.innerHTML = FILTER_KINDS.map((kind) => {
    const hidden = isKindHidden(kind);
    const label = KIND_LABELS[kind];
    return `<button
      type="button"
      class="activity-filter-chip${hidden ? "" : " is-active"}"
      data-activity-kind="${kind}"
      aria-pressed="${hidden ? "false" : "true"}"
      title="${hidden ? `Show ${label} events` : `Hide ${label} events`}"
    >${label}</button>`;
  }).join("");
}

function bindActivityFilters() {
  if (!filtersEl || filtersBound) return;
  filtersBound = true;
  filtersEl.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-activity-kind]");
    if (!btn) return;
    toggleKindHidden(btn.dataset.activityKind);
  });
}

export function renderActivityFeed(events) {
  if (!feed) return;
  latestEvents = events || [];
  loadActivityPreferences();
  bindActivityFilters();
  renderActivityFilters();

  const visible = latestEvents.filter((entry) => !isKindHidden(entry.kind));
  if (!latestEvents.length) {
    feed.innerHTML =
      '<li class="activity-item activity-item--empty">No recent activity yet.</li>';
    return;
  }
  if (!visible.length) {
    feed.innerHTML =
      '<li class="activity-item activity-item--empty">No activity matches the selected filters.</li>';
    return;
  }

  feed.innerHTML = visible
    .slice(0, 20)
    .map((entry) => {
      const kind = KIND_LABELS[entry.kind] || entry.kind || "Event";
      const user = entry.username ? `@${entry.username} · ` : "";
      return `<li class="activity-item">
        <span class="activity-time">${formatTimestamp(entry.at)}</span>
        <span class="activity-kind">${kind}</span>
        <span class="activity-message">${user}${entry.message || ""}</span>
      </li>`;
    })
    .join("");
}
