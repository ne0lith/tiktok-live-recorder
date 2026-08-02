function ffmpegPanelElements() {
  const root = document.getElementById("ffmpeg-info");
  if (!root) {
    return null;
  }
  const sourceEl = root.querySelector("#ffmpeg-source");
  const pathEl = root.querySelector("#ffmpeg-path");
  const versionEl = root.querySelector("#ffmpeg-version");
  const hevcEl = root.querySelector("#ffmpeg-hevc");
  if (!sourceEl || !pathEl || !versionEl || !hevcEl) {
    return null;
  }
  return { sourceEl, pathEl, versionEl, hevcEl };
}

export function readStartupFfmpegFromDom() {
  const dataEl = document.getElementById("startup-ffmpeg-data");
  if (!dataEl?.textContent?.trim()) {
    return null;
  }
  try {
    return JSON.parse(dataEl.textContent);
  } catch {
    return null;
  }
}

export function syncFfmpegInfo(ffmpeg) {
  const elements = ffmpegPanelElements();
  if (!elements) return;
  const { sourceEl, pathEl, versionEl, hevcEl } = elements;

  if (!ffmpeg?.path) {
    sourceEl.textContent = "Not configured";
    pathEl.textContent = "-";
    versionEl.textContent = "-";
    hevcEl.textContent = "-";
    hevcEl.className = "ffmpeg-hevc ffmpeg-hevc--unknown";
    return;
  }

  const sourceLabels = {
    vendor: "Vendor (BtbN n8.1 auto-install)",
    system: "System PATH",
    custom: "Custom path",
    missing: "Missing",
  };
  sourceEl.textContent = sourceLabels[ffmpeg.source] || ffmpeg.source;
  pathEl.textContent = ffmpeg.path;
  pathEl.title = ffmpeg.path;
  versionEl.textContent = ffmpeg.version || "-";
  if (ffmpeg.source === "vendor") {
    hevcEl.textContent = "Pinned BtbN n8.1";
    hevcEl.title = "Trusted vendor build (no runtime probe)";
    hevcEl.className = "ffmpeg-hevc ffmpeg-hevc--ok";
    return;
  }
  const probe = ffmpeg.hevc_probe;
  let hevcText = ffmpeg.hevc_capable ? "Capable" : "Not capable";
  if (probe) {
    const modes = [];
    if (probe.legacy) modes.push("legacy");
    if (probe.enhanced) modes.push("enhanced");
    if (probe.roundtrip) modes.push("roundtrip");
    if (modes.length) {
      hevcText += ` (${modes.join(" + ")})`;
    } else if (ffmpeg.hevc_capable) {
      hevcText = "Capable";
    }
  }
  hevcEl.textContent = hevcText;
  hevcEl.title = probe
    ? `legacy codec-12: ${probe.legacy ? "pass" : "fail"}; enhanced hvc1: ${probe.enhanced ? "pass" : "fail"}; libx265 FLV roundtrip: ${probe.roundtrip ? "pass" : "fail"}`
    : "";
  hevcEl.className = ffmpeg.hevc_capable
    ? "ffmpeg-hevc ffmpeg-hevc--ok"
    : "ffmpeg-hevc ffmpeg-hevc--bad";
}

export function syncStartupFfmpegFromDom() {
  const ffmpeg = readStartupFfmpegFromDom();
  if (ffmpeg?.path) {
    syncFfmpegInfo(ffmpeg);
  }
}

export function syncRuntimeControls(status) {
  const intervalInput = document.getElementById("interval-input");
  const telegramEnabled = document.getElementById("telegram-enabled");
  const maxConvertsInput = document.getElementById("max-converts-input");
  if (intervalInput && document.activeElement !== intervalInput) {
    intervalInput.value = String(status.automatic_interval_minutes ?? 5);
  }
  if (telegramEnabled && document.activeElement !== telegramEnabled) {
    telegramEnabled.checked = Boolean(status.use_telegram);
  }
  if (maxConvertsInput && document.activeElement !== maxConvertsInput) {
    maxConvertsInput.value = String(status.max_concurrent_converts ?? 1);
  }
  if (status?.ffmpeg?.path) {
    syncFfmpegInfo(status.ffmpeg);
  }
}

export function renderTelegramUploads(uploads) {
  const container = document.getElementById("telegram-uploads");
  const list = document.getElementById("telegram-uploads-list");
  if (!container || !list) return;
  if (!uploads.length) {
    container.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  container.classList.remove("hidden");
  list.innerHTML = uploads
    .slice(0, 8)
    .map(
      (entry) =>
        `<li><span class="upload-status ${entry.status}">${entry.status}</span> @${entry.username} · ${entry.file} · ${entry.message}</li>`,
    )
    .join("");
}
