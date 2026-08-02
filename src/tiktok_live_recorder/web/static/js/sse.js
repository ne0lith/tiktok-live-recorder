import { setConnectionState } from "./connection.js";
import { applyMediaUpdate } from "./media.js";
import { renderStatus } from "./status.js";
import { syncUpdateFromStatus } from "./update.js";

let eventSource = null;
let reconnectTimer = null;
let mediaFallbackTimer = null;

function clearReconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function scheduleReconnect() {
  clearReconnect();
  reconnectTimer = setTimeout(() => connectEventStream(), 3000);
}

export function connectEventStream() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  eventSource = new EventSource("/api/events");

  eventSource.onopen = () => {
    setConnectionState("ok");
    clearReconnect();
  };

  eventSource.onmessage = (event) => {
    setConnectionState("ok");
    try {
      const payload = JSON.parse(event.data);
      if (payload.type === "status" && payload.data) {
        renderStatus(payload.data);
        syncUpdateFromStatus(payload.data);
      } else if (payload.type === "media" && payload.data) {
        applyMediaUpdate(payload.data);
      }
    } catch (error) {
      console.warn("SSE payload parse failed", error);
    }
  };

  eventSource.onerror = () => {
    setConnectionState("degraded");
    eventSource?.close();
    eventSource = null;
    scheduleReconnect();
  };
}

export function disconnectEventStream() {
  clearReconnect();
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  if (mediaFallbackTimer) {
    clearInterval(mediaFallbackTimer);
    mediaFallbackTimer = null;
  }
}

export function startMediaFallback(refreshMedia) {
  if (mediaFallbackTimer) return;
  mediaFallbackTimer = setInterval(() => refreshMedia(), 60000);
}
