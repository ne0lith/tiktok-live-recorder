from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

THUMB_SUFFIX = ".thumb.jpg"
_thumb_locks: dict[str, threading.Lock] = {}
_thumb_locks_guard = threading.Lock()


def thumbnail_path_for(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}{THUMB_SUFFIX}")


def thumbnail_is_fresh(video_path: Path, thumb_path: Path) -> bool:
    if not thumb_path.is_file():
        return False
    try:
        return thumb_path.stat().st_mtime >= video_path.stat().st_mtime
    except OSError:
        return False


def thumbnail_url(username: str, filename: str, *, subdir: str | None = None) -> str:
    encoded_user = username
    encoded_file = filename
    if subdir:
        return f"/media/{encoded_user}/{subdir}/{encoded_file}/thumb"
    return f"/media/{encoded_user}/{encoded_file}/thumb"


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _thumb_locks_guard:
        lock = _thumb_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _thumb_locks[key] = lock
        return lock


def generate_thumbnail(
    video_path: Path,
    thumb_path: Path,
    *,
    ffmpeg_path: str | None,
) -> bool:
    ffmpeg_cmd = ffmpeg_path or "ffmpeg"
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = thumb_path.with_suffix(f"{thumb_path.suffix}.tmp")
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
        logger.warning("Thumbnail generation failed for %s: %s", video_path, stderr)
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
    thumb_path = thumbnail_path_for(video_path)
    if thumbnail_is_fresh(video_path, thumb_path):
        return thumb_path

    lock = _lock_for(thumb_path)
    with lock:
        if thumbnail_is_fresh(video_path, thumb_path):
            return thumb_path
        if generate_thumbnail(video_path, thumb_path, ffmpeg_path=ffmpeg_path):
            return thumb_path
    return None


def delete_thumbnail(video_path: Path) -> None:
    thumbnail_path_for(video_path).unlink(missing_ok=True)
