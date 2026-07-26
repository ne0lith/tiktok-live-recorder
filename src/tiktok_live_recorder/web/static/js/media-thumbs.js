export function createMediaThumb(item) {
  const img = document.createElement("img");
  img.className = "media-thumb media-thumb--pending";
  img.alt = "";
  img.decoding = "async";
  img.loading = "lazy";

  if (!item.thumb_url) {
    return img;
  }

  img.addEventListener(
    "load",
    () => {
      img.classList.remove("media-thumb--pending");
      img.classList.add("media-thumb--ready");
    },
    { once: true },
  );
  img.addEventListener(
    "error",
    () => {
      img.classList.remove("media-thumb--pending");
      img.classList.add("media-thumb--missing");
    },
    { once: true },
  );
  img.src = item.thumb_url;
  return img;
}

export function observeMediaThumbs(_root) {
  // Server thumbnails load via <img src>; nothing to observe.
}
