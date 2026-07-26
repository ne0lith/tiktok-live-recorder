import { formatTimestamp } from "./format.js";

const feed = document.getElementById("activity-feed");

const KIND_LABELS = {
  poll: "Poll",
  recording: "Recording",
  telegram: "Telegram",
};

export function renderActivityFeed(events) {
  if (!feed) return;
  const items = events || [];
  if (!items.length) {
    feed.innerHTML = '<li class="activity-item activity-item--empty">No recent activity yet.</li>';
    return;
  }

  feed.innerHTML = items
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
