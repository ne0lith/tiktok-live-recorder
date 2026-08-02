import { api, showToast } from "./api.js";

let lastCheckResult = null;
let applyingRestart = false;

function el(id) {
  return document.getElementById(id);
}

function scopeLabel(scope) {
  if (scope === "restart") return "Restart required";
  if (scope === "hot") return "No restart";
  return "";
}

function scopeConfirmMessage(scope) {
  if (scope === "restart") {
    return (
      "Stops polling and new recordings, waits for active streams and all " +
      "converts to finish, then restarts. Continue?"
    );
  }
  return (
    "Updates dashboard and/or release files - no restart; recordings unaffected. " +
    "Dependency changes apply on next restart. Continue?"
  );
}

export function syncUpdateFromStatus(status) {
  if (!status?.update) return;
  const update = status.update;
  const progress = el("update-progress");
  const message = el("update-progress-message");
  const applyBtn = el("update-apply-btn");
  const checkBtn = el("update-check-btn");

  if (!progress || !message) return;

  if (update.phase === "idle") {
    progress.classList.add("hidden");
    applyingRestart = false;
    if (applyBtn) applyBtn.disabled = false;
    if (checkBtn) checkBtn.disabled = false;
    return;
  }

  progress.classList.remove("hidden");
  message.textContent = update.error || update.message || update.phase;

  if (update.phase === "waiting" || update.phase === "applying" || update.phase === "restarting") {
    applyingRestart = true;
    if (applyBtn) applyBtn.disabled = true;
    if (checkBtn) checkBtn.disabled = true;
  }

  if (update.phase === "error") {
    applyingRestart = false;
    if (applyBtn) applyBtn.disabled = false;
    if (checkBtn) checkBtn.disabled = false;
    showToast(update.error || "Update failed");
  }

  if (update.phase === "restarting") {
    showToast("Restarting…");
  }
}

export async function loadUpdateInfo() {
  const runningEl = el("update-running-version");
  const repoEl = el("update-repo-version");
  const hintEl = el("update-not-updatable-hint");
  const applyBtn = el("update-apply-btn");
  const checkBtn = el("update-check-btn");
  const resultEl = el("update-check-result");

  try {
    const info = await api("/api/update");
    if (runningEl) {
      runningEl.textContent = info.running_version || "-";
    }
    if (repoEl) {
      const differs =
        info.repo_version && info.repo_version !== info.running_version;
      repoEl.textContent = differs ? info.repo_version : "";
      repoEl.classList.toggle("hidden", !differs);
    }
    if (hintEl) {
      hintEl.classList.toggle("hidden", Boolean(info.updatable));
    }
    if (applyBtn) {
      applyBtn.classList.toggle("hidden", !info.updatable);
    }
    if (checkBtn) {
      checkBtn.disabled = false;
    }
    if (resultEl && !lastCheckResult) {
      resultEl.textContent = "";
      resultEl.classList.add("hidden");
    }
    return info;
  } catch (error) {
    console.warn("Update info fetch failed", error);
    return null;
  }
}

function renderCheckResult(result) {
  const resultEl = el("update-check-result");
  const scopeEl = el("update-scope-badge");
  const applyBtn = el("update-apply-btn");
  if (!resultEl) return;

  lastCheckResult = result;
  const parts = [];
  if (result.update_available) {
    parts.push(`v${result.latest} available (running v${result.current})`);
  } else {
    parts.push(`Up to date (v${result.current})`);
  }
  if (result.scope) {
    parts.push(scopeLabel(result.scope));
  }
  resultEl.textContent = parts.join(" · ");
  resultEl.classList.remove("hidden");

  if (scopeEl) {
    const label = scopeLabel(result.scope);
    scopeEl.textContent = label;
    scopeEl.classList.toggle("hidden", !label);
    scopeEl.dataset.scope = result.scope || "";
  }

  if (applyBtn) {
    const canApply =
      Boolean(result.updatable) &&
      (result.update_available || (result.changed_files?.length ?? 0) > 0);
    applyBtn.disabled = !canApply || applyingRestart;
  }
}

export async function checkForUpdates() {
  const checkBtn = el("update-check-btn");
  try {
    checkBtn?.classList.add("is-loading");
    const result = await api("/api/update/check", { method: "POST" });
    renderCheckResult(result);
    return result;
  } finally {
    checkBtn?.classList.remove("is-loading");
  }
}

export async function applyUpdate() {
  if (!lastCheckResult) {
    await checkForUpdates();
  }
  const scope = lastCheckResult?.scope || "hot";
  if (!window.confirm(scopeConfirmMessage(scope))) {
    return;
  }

  const applyBtn = el("update-apply-btn");
  try {
    applyBtn?.classList.add("is-loading");
    applyBtn.disabled = true;
    const result = await api("/api/update/apply", { method: "POST" });

    if (result.scope === "restart") {
      applyingRestart = true;
      showToast(result.message || "Update started");
      const progress = el("update-progress");
      const message = el("update-progress-message");
      progress?.classList.remove("hidden");
      if (message) message.textContent = result.message || "Waiting…";
      return result;
    }

    showToast(result.message || "Update applied");
    await loadUpdateInfo();
    if (result.static_changed) {
      window.location.reload();
    }
    return result;
  } catch (error) {
    showToast(error.message);
    throw error;
  } finally {
    applyBtn?.classList.remove("is-loading");
    if (!applyingRestart && applyBtn) {
      applyBtn.disabled = !(
        lastCheckResult?.update_available ||
        (lastCheckResult?.changed_files?.length ?? 0) > 0
      );
    }
  }
}

export function initUpdateInteractions() {
  el("update-check-btn")?.addEventListener("click", async () => {
    try {
      await checkForUpdates();
    } catch (error) {
      showToast(error.message);
    }
  });

  el("update-apply-btn")?.addEventListener("click", async () => {
    try {
      await applyUpdate();
    } catch (error) {
      // toast shown in applyUpdate
    }
  });
}
