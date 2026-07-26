const DB_NAME = "ttlr-media-thumbs";
const STORE = "thumbs";
const DB_VERSION = 1;
const MAX_CONCURRENT = 3;
const JPEG_QUALITY = 0.72;

const memoryCache = new Map();
const pendingKeys = new Set();
const queue = [];
let inFlight = 0;
let observer = null;
let dbPromise = null;

function thumbKey(item) {
  return `${item.url}|${item.modified_at || 0}`;
}

function openDb() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      if (!window.indexedDB) {
        resolve(null);
        return;
      }
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        request.result.createObjectStore(STORE);
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  return dbPromise;
}

async function readPersistedThumb(key) {
  const db = await openDb();
  if (!db) return null;
  return new Promise((resolve) => {
    const tx = db.transaction(STORE, "readonly");
    const store = tx.objectStore(STORE);
    const request = store.get(key);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => resolve(null);
  });
}

async function writePersistedThumb(key, dataUrl) {
  const db = await openDb();
  if (!db) return;
  return new Promise((resolve) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(dataUrl, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => resolve();
  });
}

function rememberThumb(key, dataUrl) {
  memoryCache.set(key, dataUrl);
  writePersistedThumb(key, dataUrl);
}

function applyThumb(img, dataUrl) {
  img.src = dataUrl;
  img.classList.remove("media-thumb--pending");
  img.classList.add("media-thumb--ready");
}

async function captureVideoThumb(url) {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.preload = "metadata";

    const cleanup = () => {
      video.removeAttribute("src");
      video.load();
    };

    video.addEventListener(
      "loadeddata",
      () => {
        try {
          video.currentTime = 0.1;
        } catch (error) {
          cleanup();
          reject(error);
        }
      },
      { once: true },
    );

    video.addEventListener(
      "seeked",
      () => {
        try {
          const width = video.videoWidth || 160;
          const height = video.videoHeight || 90;
          const canvas = document.createElement("canvas");
          canvas.width = width;
          canvas.height = height;
          const ctx = canvas.getContext("2d");
          if (!ctx) {
            cleanup();
            reject(new Error("canvas unavailable"));
            return;
          }
          ctx.drawImage(video, 0, 0, width, height);
          const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
          cleanup();
          resolve(dataUrl);
        } catch (error) {
          cleanup();
          reject(error);
        }
      },
      { once: true },
    );

    video.addEventListener(
      "error",
      () => {
        cleanup();
        reject(new Error("thumb video load failed"));
      },
      { once: true },
    );

    video.src = url;
  });
}

function schedule(task) {
  queue.push(task);
  drainQueue();
}

function drainQueue() {
  while (inFlight < MAX_CONCURRENT && queue.length) {
    inFlight += 1;
    const task = queue.shift();
    task().finally(() => {
      inFlight -= 1;
      drainQueue();
    });
  }
}

async function resolveThumb(item) {
  const key = thumbKey(item);
  if (memoryCache.has(key)) {
    return memoryCache.get(key);
  }
  const persisted = await readPersistedThumb(key);
  if (persisted) {
    memoryCache.set(key, persisted);
    return persisted;
  }
  if (pendingKeys.has(key)) {
    return null;
  }
  pendingKeys.add(key);
  try {
    const dataUrl = await captureVideoThumb(item.url);
    rememberThumb(key, dataUrl);
    return dataUrl;
  } catch {
    return null;
  } finally {
    pendingKeys.delete(key);
  }
}

function loadThumbForImage(img, item) {
  const key = thumbKey(item);
  const cached = memoryCache.get(key);
  if (cached) {
    applyThumb(img, cached);
    return;
  }

  schedule(async () => {
    if (!img.isConnected) return;
    const dataUrl = await resolveThumb(item);
    if (dataUrl && img.isConnected && thumbKey(item) === key) {
      applyThumb(img, dataUrl);
    }
  });
}

function ensureObserver() {
  if (observer) return observer;
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const img = entry.target;
        const item = {
          url: img.dataset.thumbUrl,
          modified_at: Number(img.dataset.thumbModified || 0),
        };
        if (!item.url) continue;
        observer.unobserve(img);
        loadThumbForImage(img, item);
      }
    },
    { rootMargin: "120px 0px", threshold: 0.01 },
  );
  return observer;
}

export function createMediaThumb(item) {
  const img = document.createElement("img");
  img.className = "media-thumb media-thumb--pending";
  img.alt = "";
  img.decoding = "async";
  img.loading = "lazy";
  img.dataset.thumbUrl = item.url;
  img.dataset.thumbModified = String(item.modified_at || 0);

  const key = thumbKey(item);
  const cached = memoryCache.get(key);
  if (cached) {
    applyThumb(img, cached);
    return img;
  }

  void (async () => {
    const persisted = await readPersistedThumb(key);
    if (!img.isConnected) return;
    if (persisted) {
      memoryCache.set(key, persisted);
      applyThumb(img, persisted);
      return;
    }
    ensureObserver().observe(img);
  })();

  return img;
}

export function observeMediaThumbs(root) {
  if (!root) return;
  const obs = ensureObserver();
  root.querySelectorAll("img.media-thumb--pending").forEach((img) => {
    if (!img.src) obs.observe(img);
  });
}
