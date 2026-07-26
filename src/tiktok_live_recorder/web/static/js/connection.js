const listeners = new Set();
let connectionState = "ok";

export function getConnectionState() {
  return connectionState;
}

export function onConnectionChange(listener) {
  listeners.add(listener);
  listener(connectionState);
  return () => listeners.delete(listener);
}

export function setConnectionState(state) {
  if (connectionState === state) return;
  connectionState = state;
  listeners.forEach((listener) => listener(state));
}

const banner = () => document.getElementById("connection-banner");
const bannerText = () => document.getElementById("connection-banner-text");
const bannerRetry = () => document.getElementById("connection-banner-retry");

export function initConnectionBanner() {
  onConnectionChange((state) => {
    const el = banner();
    if (!el) return;
    el.classList.toggle("hidden", state === "ok");
    if (bannerText()) {
      bannerText().textContent =
        state === "offline"
          ? "Dashboard is offline - check the recorder and your network."
          : "Dashboard is having trouble reaching the recorder - retrying…";
    }
  });

  bannerRetry()?.addEventListener("click", () => {
    window.dispatchEvent(new CustomEvent("ttlr:retry-connection"));
  });
}
