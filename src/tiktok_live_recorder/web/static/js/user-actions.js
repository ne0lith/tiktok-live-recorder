import { api, showToast } from "./api.js";
import { usernamesMatch } from "./format.js";

export function isUserInWatchlist(username, status) {
  return (status?.users || []).some((u) => usernamesMatch(u, username));
}

export function isUserPaused(username, status) {
  return (status?.paused || []).some((u) => usernamesMatch(u, username));
}

export function getUserRecordingState(username, status) {
  const entry = (status?.recordings || []).find((r) => usernamesMatch(r.username, username));
  if (!entry || entry.is_alive === false) return null;
  return entry.status || "recording";
}

function canStopUser(username, status, row = null) {
  if (row) {
    return (
      row.state === "recording" ||
      row.state === "convert_queued" ||
      row.state === "converting" ||
      row.state === "stopping"
    );
  }
  const state = getUserRecordingState(username, status);
  return (
    state === "recording" ||
    state === "convert_queued" ||
    state === "converting" ||
    state === "stopping"
  );
}

export function profileLinkMarkup(username, { active = false } = {}) {
  return `<button type="button" class="profile-link${active ? " is-active" : ""}" data-profile="${username}">@${username}</button>`;
}

export function buildUserActionButtons(username, status, row = null, { context = "status" } = {}) {
  if (!username || username.toLowerCase() === "unknown") return "";

  const mode = status?.mode || "watchlist";
  if (context === "player" && mode !== "watchlist") return "";

  const inWatchlist = isUserInWatchlist(username, status);
  const paused = isUserPaused(username, status);
  const canStop = canStopUser(username, status, row);
  const buttons = [];

  if (!inWatchlist) {
    if (mode === "watchlist") {
      buttons.push(
        `<button class="btn btn-ghost btn-small" data-action="add" data-user="${username}">Add to watchlist</button>`,
      );
    }
    return buttons.length ? `<div class="status-actions">${buttons.join("")}</div>` : "";
  }

  if (canStop) {
    buttons.push(
      `<button class="btn btn-danger btn-small" data-action="stop" data-user="${username}">Stop</button>`,
    );
  }
  buttons.push(
    paused
      ? `<button class="btn btn-ghost btn-small" data-action="resume" data-user="${username}">Resume</button>`
      : `<button class="btn btn-ghost btn-small" data-action="pause" data-user="${username}">Pause</button>`,
  );
  if (mode === "watchlist") {
    buttons.push(
      `<button class="btn btn-ghost btn-small" data-action="check" data-user="${username}" title="Check if this user is live now">Check</button>`,
    );
    buttons.push(
      `<button class="btn btn-ghost btn-small" data-action="remove" data-user="${username}">Remove</button>`,
    );
  }

  return `<div class="status-actions">${buttons.join("")}</div>`;
}

export async function runUserAction(action, username, { onSuccess } = {}) {
  const user = username;
  try {
    if (action === "stop") {
      await api(`/api/recordings/${encodeURIComponent(user)}/stop`, { method: "POST" });
      showToast(`Stopping @${user}`);
    } else if (action === "pause") {
      await api(`/api/users/${encodeURIComponent(user)}/pause`, { method: "POST" });
      showToast(`Paused @${user}`);
    } else if (action === "resume") {
      await api(`/api/users/${encodeURIComponent(user)}/resume`, { method: "POST" });
      showToast(`Resumed @${user}`);
    } else if (action === "check") {
      await api(`/api/users/${encodeURIComponent(user)}/poll`, { method: "POST" });
      showToast(`Checking @${user}`);
    } else if (action === "add") {
      await api("/api/users", {
        method: "POST",
        body: JSON.stringify({ username: user }),
      });
      showToast(`Added @${user.replace(/^@/, "")}`);
    } else if (action === "remove") {
      if (!confirm(`Remove @${user} from the watchlist?`)) return;
      await api(`/api/users/${encodeURIComponent(user)}`, { method: "DELETE" });
      showToast(`Removed @${user}`);
    } else {
      return;
    }
    if (onSuccess) await onSuccess();
  } catch (error) {
    showToast(error.message);
  }
}
