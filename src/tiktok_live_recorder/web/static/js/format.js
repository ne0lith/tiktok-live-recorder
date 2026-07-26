export function formatBytes(bytes) {
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

export function formatDuration(seconds) {
  if (seconds == null) return "-";
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function formatTimestamp(epoch) {
  if (!epoch) return "Never";
  return new Date(epoch * 1000).toLocaleString();
}

export function formatNextPoll(status) {
  if (!status?.last_poll_at || !status?.automatic_interval_minutes) return "-";
  const nextAt = status.last_poll_at + status.automatic_interval_minutes * 60;
  const remaining = Math.max(0, Math.ceil(nextAt - Date.now() / 1000));
  if (remaining < 60) return `~${remaining}s`;
  return `~${Math.ceil(remaining / 60)}m`;
}

export function basename(path) {
  if (!path) return "";
  const parts = String(path).split(/[/\\]/);
  return parts[parts.length - 1] || path;
}

export function normalizeUsername(username) {
  return String(username || "")
    .replace(/^@+/, "")
    .trim();
}

export function usernamesMatch(a, b) {
  return normalizeUsername(a).toLowerCase() === normalizeUsername(b).toLowerCase();
}

export function tiktokProfileUrl(username) {
  return `https://tiktok.com/@${encodeURIComponent(normalizeUsername(username))}`;
}
