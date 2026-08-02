import { setConnectionState } from "./connection.js";
import { API_TIMEOUT_MS } from "./state.js";

let toastEl = null;

export function bindToast(element) {
  toastEl = element;
}

function parseApiError(text, status) {
  try {
    const data = JSON.parse(text);
    const detail = data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => item.msg || item.message || JSON.stringify(item))
        .join("; ");
    }
  } catch {
    // not JSON
  }
  return text || `Request failed (${status})`;
}

export async function api(path, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      cache: options.cache ?? "no-store",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      signal: controller.signal,
      ...options,
    });
    if (!response.ok) {
      const detail = await response.text();
      setConnectionState("degraded");
      throw new Error(parseApiError(detail, response.status));
    }
    setConnectionState("ok");
    if (response.status === 204) return null;
    return response.json();
  } catch (error) {
    if (error.name === "AbortError") {
      setConnectionState("offline");
      throw new Error("Request timed out - recorder may be busy or network is down");
    }
    if (!(error instanceof Error) || !error.message.startsWith("Request failed")) {
      setConnectionState("offline");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

export function showToast(message) {
  if (!toastEl) return;
  toastEl.textContent = message;
  toastEl.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toastEl.classList.add("hidden"), 2600);
}
