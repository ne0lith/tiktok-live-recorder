from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Iterable
from pathlib import Path

from tiktok_live_recorder.utils.ffmpeg_setup import ffprobe_for

logger = logging.getLogger(__name__)

THUMB_SUFFIX = ".thumb.jpg"
# In-flight / leftover generate temps (current + 8.15.0 misnamed muxer temp).
_TEMP_THUMB_SUFFIXES = (".thumb.tmp.jpg", ".thumb.jpg.tmp")
PROBE_TIMEOUT_SECONDS = 15
_thumb_locks: dict[str, threading.Lock] = {}
_thumb_locks_guard = threading.Lock()
_thumb_probe_failures: dict[tuple[str, float], bool] = {}
_thumb_probe_guard = threading.Lock()


def thumbnail_path_for(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}{THUMB_SUFFIX}")


def source_video_for_thumb_file(thumb_path: Path) -> Path | None:
    """Sibling ``.mp4`` that this cache/temp file belongs to, or None if the name is unknown."""
    name = thumb_path.name
    stem = None
    for suffix in _TEMP_THUMB_SUFFIXES:
        if name.endswith(suffix):
            stem = name[: -len(suffix)]
            break
    if stem is None and name.endswith(THUMB_SUFFIX):
        stem = name[: -len(THUMB_SUFFIX)]
    if not stem:
        return None
    return thumb_path.with_name(f"{stem}.mp4")


def _iter_thumbnail_cache_files(directory: Path) -> Iterable[Path]:
    if not directory.is_dir():
        return
    for pattern in ("*" + THUMB_SUFFIX, "*.thumb.tmp.jpg", "*.thumb.jpg.tmp"):
        yield from directory.glob(pattern)


def thumbnail_is_fresh(video_path: Path, thumb_path: Path) -> bool:
    if not thumb_path.is_file():
        return False
    try:
        return thumb_path.stat().st_mtime >= video_path.stat().st_mtime
    except OSError:
        return False


def thumbnail_url(username: str, filename: str, *, subdir: str | None = None) -> str:
    from urllib.parse import quote

    encoded_user = quote(username, safe="")
    encoded_file = quote(filename, safe="")
    if subdir:
        return f"/media/{encoded_user}/{quote(subdir, safe='')}/{encoded_file}/thumb"
    return f"/media/{encoded_user}/{encoded_file}/thumb"


def is_flv_recording(video_path: Path) -> bool:
    return video_path.name.endswith("_flv.mp4")


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _thumb_locks_guard:
        lock = _thumb_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thumb_locks[key] = lock
        return lock


def _probe_cache_key(video_path: Path) -> tuple[str, float] | None:
    try:
        return str(video_path.resolve()), video_path.stat().st_mtime
    except OSError:
        return None


def _is_probe_failure_cached(video_path: Path) -> bool:
    key = _probe_cache_key(video_path)
    if key is None:
        return False
    with _thumb_probe_guard:
        return _thumb_probe_failures.get(key, False)


def _cache_probe_failure(video_path: Path) -> bool:
    """Cache an unplayable file. Returns True when this is the first failure."""
    key = _probe_cache_key(video_path)
    if key is None:
        return True
    with _thumb_probe_guard:
        already_cached = _thumb_probe_failures.get(key, False)
        _thumb_probe_failures[key] = True
        return not already_cached


def clear_thumbnail_probe_cache() -> None:
    """Test helper: reset negative probe cache."""
    with _thumb_probe_guard:
        _thumb_probe_failures.clear()


def video_has_decodable_video(video_path: Path, *, ffmpeg_path: str | None) -> bool:
    ffprobe_cmd = ffprobe_for(ffmpeg_path or "ffmpeg")
    command = [
        ffprobe_cmd,
        "-hide_banner",
        "-loglevel",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return False
    return "video" in (result.stdout or "").lower()


def _temp_thumbnail_path(thumb_path: Path) -> Path:
    # Keep a .jpg extension so ffmpeg can infer the muxer (not .jpg.tmp).
    return thumb_path.with_name(f"{thumb_path.stem}.tmp{thumb_path.suffix}")


def _log_unplayable_video(video_path: Path, detail: str) -> None:
    if _cache_probe_failure(video_path):
        logger.warning("Thumbnail skipped for %s: %s", video_path, detail)
    else:
        logger.debug("Thumbnail skipped (cached unplayable) for %s", video_path)


def generate_thumbnail(
    video_path: Path,
    thumb_path: Path,
    *,
    ffmpeg_path: str | None,
) -> bool:
    ffmpeg_cmd = ffmpeg_path or "ffmpeg"
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    # Clean up legacy bad temp names from 8.15.0 (.thumb.jpg.tmp).
    thumb_path.with_suffix(f"{thumb_path.suffix}.tmp").unlink(missing_ok=True)
    temp_path = _temp_thumbnail_path(thumb_path)
    command = [
        ffmpeg_cmd,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "0.1",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=320:-2",
        "-q:v",
        "4",
        "-f",
        "image2",
        str(temp_path),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or str(exc)
        _log_unplayable_video(video_path, stderr.strip())
        temp_path.unlink(missing_ok=True)
        return False

    try:
        temp_path.replace(thumb_path)
    except OSError as exc:
        logger.warning("Could not write thumbnail for %s: %s", video_path, exc)
        temp_path.unlink(missing_ok=True)
        return False
    return True


def ensure_thumbnail(
    video_path: Path,
    *,
    ffmpeg_path: str | None,
) -> Path | None:
    if is_flv_recording(video_path):
        return None

    thumb_path = thumbnail_path_for(video_path)
    if thumbnail_is_fresh(video_path, thumb_path):
        return thumb_path

    if _is_probe_failure_cached(video_path):
        logger.debug("Thumbnail skipped (cached unplayable) for %s", video_path)
        return None

    lock = _lock_for(thumb_path)
    with lock:
        if thumbnail_is_fresh(video_path, thumb_path):
            return thumb_path
        if _is_probe_failure_cached(video_path):
            logger.debug("Thumbnail skipped (cached unplayable) for %s", video_path)
            return None
        if not video_has_decodable_video(video_path, ffmpeg_path=ffmpeg_path):
            _log_unplayable_video(video_path, "no decodable video stream")
            return None
        if generate_thumbnail(video_path, thumb_path, ffmpeg_path=ffmpeg_path):
            return thumb_path
    return None


def delete_thumbnail(video_path: Path) -> None:
    thumbnail_path_for(video_path).unlink(missing_ok=True)


def purge_orphan_thumbnails(directories: Iterable[Path]) -> int:
    """Delete ``*.thumb.jpg`` (and leftover generate temps) whose sibling ``.mp4`` is gone.

    Safe to run on library refresh: files with a live recording still in place are kept.
    """
    deleted = 0
    seen: set[str] = set()
    for directory in directories:
        try:
            root = directory.resolve()
        except OSError:
            root = directory
        if not root.is_dir():
            continue
        for path in _iter_thumbnail_cache_files(root):
            if not path.is_file():
                continue
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            video = source_video_for_thumb_file(path)
            if video is not None and video.is_file():
                continue
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Could not delete orphan thumbnail %s: %s", path, exc)
                continue
            deleted += 1
    if deleted:
        logger.info("Removed %s orphan media thumbnail(s)", deleted)
    return deleted


def reset_thumbnail_state(video_path: Path) -> None:
    """Drop cached thumbnail and unplayable-probe state after a successful repair."""
    delete_thumbnail(video_path)
    key = _probe_cache_key(video_path)
    if key is None:
        return
    with _thumb_probe_guard:
        _thumb_probe_failures.pop(key, None)
