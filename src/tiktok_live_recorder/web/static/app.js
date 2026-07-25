const statusBody = document.getElementById("status-body");
const statusMeta = document.getElementById("status-meta");
const mediaLibrary = document.getElementById("media-library");
const toast = document.getElementById("toast");

let latestStatus = null;

function showToast(message) {
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function formatBytes(bytes) {
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

function formatDuration(seconds) {
  if (seconds == null) return "-";
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatTimestamp(epoch) {
  if (!epoch) return "Never";
  return new Date(epoch * 1000).toLocaleString();
}

function deriveRows(status) {
  const paused = new Set((status.paused || []).map((u) => u.toLowerCase()));
  const recordings = new Map(
    (status.recordings || []).map((entry) => [entry.username, entry]),
  );
  const poll = status.poll || {};
  const rows = new Map();

  const ensure = (username, state) => {
    const key = username.toLowerCase();
    if (!rows.has(key)) {
      rows.set(key, {
        username,
        state,
        room_id: null,
        elapsed_seconds: null,
        bytes_written: null,
      });
    }
    return rows.get(key);
  };

  (status.users || []).forEach((username) => {
    const row = ensure(username, paused.has(username.toLowerCase()) ? "paused" : "offline");
    if (paused.has(username.toLowerCase())) row.state = "paused";
  });

  (poll.recording || []).forEach((username) => {
    ensure(username, "recording").state = "recording";
  });
  (poll.offline || []).forEach((username) => {
    const row = ensure(username, "offline");
    if (!paused.has(username.toLowerCase())) row.state = "offline";
  });
  (poll.paused || []).forEach((username) => {
    ensure(username, "paused").state = "paused";
  });
  (poll.errors || []).forEach((entry) => {
    const username = String(entry).split(" ")[0];
    ensure(username, "error").state = "error";
  });
  (poll.starting || []).forEach((entry) => {
    const row = ensure(entry.username, "live");
    row.state = "live";
    row.room_id = entry.room_id;
  });

  recordings.forEach((entry, username) => {
    const row = ensure(username, entry.status || "recording");
    row.state = entry.status || row.state;
    row.room_id = entry.room_id || row.room_id;
    row.elapsed_seconds = entry.elapsed_seconds;
    row.bytes_written = entry.bytes_written;
  });

  return Array.from(rows.values()).sort((a, b) =>
    a.username.localeCompare(b.username),
  );
}

function renderStatus(status) {
  latestStatus = status;
  const rows = deriveRows(status);
  statusMeta.textContent = `${status.mode} · last poll ${formatTimestamp(
    status.last_poll_at,
  )} · interval ${status.automatic_interval_minutes} min`;

  if (!rows.length) {
    statusBody.innerHTML =
      '<tr><td colspan="6" class="empty">No users in watchlist yet.</td></tr>';
    return;
  }

  statusBody.innerHTML = rows
    .map((row) => {
      const paused = (status.paused || [])
        .map((u) => u.toLowerCase())
        .includes(row.username.toLowerCase());
      const isWatchlist = status.mode === "watchlist";
      const actions = [];
      if (row.state === "recording" || row.state === "converting" || row.state === "stopping") {
        actions.push(
          `<button class="btn btn-danger btn-small" data-action="stop" data-user="${row.username}">Stop</button>`,
        );
      }
      if (paused) {
        actions.push(
          `<button class="btn btn-ghost btn-small" data-action="resume" data-user="${row.username}">Resume</button>`,
        );
      } else {
        actions.push(
          `<button class="btn btn-ghost btn-small" data-action="pause" data-user="${row.username}">Pause</button>`,
        );
      }
      if (isWatchlist) {
        actions.push(
          `<button class="btn btn-ghost btn-small" data-action="remove" data-user="${row.username}">Remove</button>`,
        );
      }
      return `
        <tr>
          <td class="username">@${row.username}</td>
          <td><span class="badge ${row.state}">${row.state}</span></td>
          <td>${row.room_id || "-"}</td>
          <td>${formatDuration(row.elapsed_seconds)}</td>
          <td>${formatBytes(row.bytes_written)}</td>
          <td><div class="actions">${actions.join("")}</div></td>
        </tr>
      `;
    })
    .join("");
}

function renderMedia(media) {
  const usernames = Object.keys(media || {});
  if (!usernames.length) {
    mediaLibrary.innerHTML = '<p class="empty">No recordings yet.</p>';
    return;
  }

  mediaLibrary.innerHTML = usernames
    .map((username) => {
      const items = media[username]
        .map(
          (item) => `
            <article class="media-item">
              <video controls preload="metadata" src="${item.url}"></video>
              <div class="media-meta">
                <div>${item.filename}</div>
                <div>${formatBytes(item.size)} · ${formatTimestamp(item.modified_at)}${
                  item.in_progress ? " · in progress" : ""
                }${item.source === "legacy" ? " · legacy" : ""}</div>
              </div>
            </article>
          `,
        )
        .join("");
      return `
        <section class="user-section">
          <h3>@${username}</h3>
          <div class="media-grid">${items}</div>
        </section>
      `;
    })
    .join("");
}

async function refreshStatus() {
  const status = await api("/api/status");
  renderStatus(status);
}

async function refreshMedia() {
  const media = await api("/api/media");
  renderMedia(media);
}

statusBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const { action, user } = button.dataset;
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
    } else if (action === "remove") {
      await api(`/api/users/${encodeURIComponent(user)}`, { method: "DELETE" });
      showToast(`Removed @${user}`);
    }
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("add-user-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("add-user-input");
  const username = input.value.trim();
  if (!username) return;
  try {
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({ username }),
    });
    input.value = "";
    showToast(`Added @${username.replace(/^@/, "")}`);
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("force-poll-btn").addEventListener("click", async () => {
  try {
    await api("/api/poll", { method: "POST" });
    showToast("Poll requested");
    await refreshStatus();
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("refresh-media-btn").addEventListener("click", async () => {
  try {
    await refreshMedia();
    showToast("Media refreshed");
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("settings-toggle").addEventListener("click", () => {
  document.getElementById("settings-panel").classList.toggle("hidden");
});

async function loadSettings() {
  const [cookies, telegram] = await Promise.all([
    api("/api/settings/cookies"),
    api("/api/settings/telegram"),
  ]);
  document.getElementById("cookies-editor").value = JSON.stringify(
    cookies.cookies || {},
    null,
    2,
  );
  document.getElementById("telegram-editor").value = JSON.stringify(
    telegram.telegram || {},
    null,
    2,
  );
}

document.getElementById("save-cookies-btn").addEventListener("click", async () => {
  try {
    const cookies = JSON.parse(document.getElementById("cookies-editor").value);
    await api("/api/settings/cookies", {
      method: "PUT",
      body: JSON.stringify({ cookies }),
    });
    showToast("Cookies saved");
  } catch (error) {
    showToast(error.message);
  }
});

document.getElementById("save-telegram-btn").addEventListener("click", async () => {
  try {
    const telegram = JSON.parse(document.getElementById("telegram-editor").value);
    await api("/api/settings/telegram", {
      method: "PUT",
      body: JSON.stringify({ telegram }),
    });
    showToast("Telegram settings saved");
  } catch (error) {
    showToast(error.message);
  }
});

async function boot() {
  try {
    await Promise.all([refreshStatus(), refreshMedia(), loadSettings()]);
  } catch (error) {
    showToast(error.message);
  }
  setInterval(refreshStatus, 2500);
  setInterval(refreshMedia, 15000);
}

boot();
