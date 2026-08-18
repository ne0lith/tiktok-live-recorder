import re
import shutil
import threading
from pathlib import Path
from urllib.parse import quote

from tiktok_live_recorder.utils.logger_manager import logger
from tiktok_live_recorder.utils.video_management import VideoManagement
from tiktok_live_recorder.web.codec_index import (
    configure_codec_index,
    get_codec_index,
    reset_codec_index,
)
from tiktok_live_recorder.web.thumbnails import purge_orphan_thumbnails, thumbnail_url

# Username may contain underscores (including a leading `_`); anchor on the
# recorder timestamp so we do not stop at the first `_` after `TK_`.
MEDIA_PATTERN = re.compile(
    r"^TK_(?P<username>.+)_\d{4}\.\d{2}\.\d{2}_\d{2}-\d{2}-\d{2}(?:_flv)?\.mp4$",
    re.IGNORECASE,
)
LEGACY_SUBDIR = "legacy"
# In-flight encodes written beside the finished TK_*.mp4; never list or serve these.
_TRANSIENT_MEDIA_SUFFIXES = (".repair.tmp.mp4", ".av1temp.mp4")
_JOB_STATUSES = frozenset({"queued", "converting"})


def unique_to_fix_dest(dest_dir: Path, filename: str) -> Path:
    """Return dest_dir/filename, or dest_dir/stem.N.suffix if that name exists."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 1
    while True:
        candidate = dest_dir / f"{stem}.{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _cached_library_playable(path: Path, ffprobe_cmd: str) -> bool:
    codec, pix_fmt = get_codec_index().get_or_probe(path, ffprobe_cmd)
    return VideoManagement.library_playable_from_probe(codec, pix_fmt)


def clear_library_playable_cache() -> None:
    get_codec_index().clear()
    reset_codec_index()


def _is_transient_media_name(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(suffix) for suffix in _TRANSIENT_MEDIA_SUFFIXES)


def _is_safe_filename(filename: str) -> bool:
    """Reject path separators / traversal names, not embedded '..' in TikTok usernames."""
    if not filename or filename in {".", ".."}:
        return False
    if "/" in filename or "\\" in filename:
        return False
    # Path(filename).name strips dirs; mismatch means a separator slipped through.
    if Path(filename).name != filename:
        return False
    if _is_transient_media_name(filename):
        return False
    return filename.lower().endswith(".mp4")


def _is_safe_username(username: str) -> bool:
    if not username or username in {".", ".."}:
        return False
    if "/" in username or "\\" in username:
        return False
    return Path(username).name == username


def _encoded_media_url(
    username: str, filename: str, *, subdir: str | None = None
) -> str:
    user = quote(username, safe="")
    name = quote(filename, safe="")
    if subdir:
        return f"/media/{user}/{quote(subdir, safe='')}/{name}"
    return f"/media/{user}/{name}"


def _flv_to_mp4_path(path: str) -> str:
    """Destination path ffmpeg writes while converting a ``*_flv.mp4`` source."""
    if path.endswith("_flv.mp4"):
        return path[: -len("_flv.mp4")] + ".mp4"
    return path


def _normalize_active_paths(active_output_paths: set[str] | None) -> set[str]:
    """Resolve active paths and include in-flight conversion destinations.

    Convert jobs track the ``*_flv.mp4`` source, but ffmpeg writes the final
    ``.mp4`` concurrently — both must be treated as in-progress.
    """
    normalized: set[str] = set()
    for path in active_output_paths or ():
        try:
            resolved = str(Path(path).resolve())
        except OSError:
            resolved = str(path)
        normalized.add(resolved)
        if resolved.endswith("_flv.mp4"):
            normalized.add(_flv_to_mp4_path(resolved))
    return normalized


def av1temp_sibling(path: Path) -> Path:
    """Sibling temp written by an external AV1 encoder beside a library MP4."""
    name = path.name
    if name.lower().endswith(".mp4"):
        return path.with_name(name[:-4] + ".av1temp.mp4")
    return path.with_name(name + ".av1temp.mp4")


def _job_status_map(media_jobs: list[dict] | None) -> dict[str, str]:
    """Map resolved library paths (including FLV convert destinations) to job status."""
    mapped: dict[str, str] = {}
    for job in media_jobs or ():
        path = job.get("path")
        status = job.get("status")
        if not path or status not in _JOB_STATUSES:
            continue
        try:
            resolved = str(Path(path).resolve())
        except OSError:
            resolved = str(path)
        mapped[resolved] = status
        if resolved.endswith("_flv.mp4"):
            mapped[_flv_to_mp4_path(resolved)] = status
    return mapped


def _media_entry(
    path: Path,
    username: str,
    *,
    subdir: str | None = None,
    active_paths: set[str] | None = None,
    ffprobe_cmd: str = "ffprobe",
    media_jobs: dict[str, str] | None = None,
    inventory: bool = False,
) -> dict:
    stat = path.stat()
    url = _encoded_media_url(username, path.name, subdir=subdir)
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    is_flv = path.name.endswith("_flv.mp4")
    is_active = resolved in (active_paths or set())
    needs_convert = is_flv and not is_active
    if is_active:
        repairable = False
    elif needs_convert:
        repairable = True
    elif inventory:
        repairable = False
    else:
        # Already H.264/AV1: not repairable (server must not re-encode AV1 to H.264).
        repairable = not _cached_library_playable(path, ffprobe_cmd)
    entry = {
        "filename": path.name,
        "username": username,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        # Any path in active_paths (raw FLV *or* partial convert destination).
        "in_progress": is_active,
        "needs_convert": needs_convert,
        "repairable": repairable,
        "source": subdir or "recordings",
        "url": url,
        "path": resolved,
    }
    if not entry["in_progress"] and not is_flv:
        entry["thumb_url"] = thumbnail_url(username, path.name, subdir=subdir)
    if inventory:
        _attach_inventory_fields(
            entry,
            path,
            resolved,
            is_flv=is_flv,
            is_active=is_active,
            ffprobe_cmd=ffprobe_cmd,
            media_jobs=media_jobs,
            skip_probe=is_active or stat.st_size <= 0,
        )
    return entry


def _attach_inventory_fields(
    entry: dict,
    path: Path,
    resolved: str,
    *,
    is_flv: bool,
    is_active: bool,
    ffprobe_cmd: str,
    media_jobs: dict[str, str] | None,
    skip_probe: bool,
) -> None:
    job_status = (media_jobs or {}).get(resolved)
    has_av1temp = (not is_flv) and av1temp_sibling(path).is_file()
    converting = False
    busy_reason: str | None = None
    if job_status in _JOB_STATUSES:
        busy_reason = job_status
        converting = True
    elif is_active:
        busy_reason = "recording"
    elif has_av1temp:
        busy_reason = "av1temp"
        converting = True

    index = get_codec_index()
    disappeared = index.note_av1temp(resolved, has_av1temp)
    codec, pix_fmt = index.get_or_probe(
        path,
        ffprobe_cmd,
        skip_probe=skip_probe,
        force=bool(disappeared and not skip_probe),
    )
    if not is_active and not entry["needs_convert"]:
        entry["repairable"] = not VideoManagement.library_playable_from_probe(
            codec, pix_fmt
        )
    entry["codec"] = codec
    entry["pix_fmt"] = pix_fmt
    entry["is_av1"] = codec == "av1"
    entry["converting"] = converting
    entry["busy_reason"] = busy_reason


def _is_inventory_ready(entry: dict) -> bool:
    if entry["filename"].endswith("_flv.mp4"):
        return False
    if entry.get("is_av1"):
        return False
    if entry.get("in_progress") or entry.get("converting"):
        return False
    return True


def _append_library_entry(
    entries: list[dict],
    path: Path,
    username: str,
    *,
    subdir: str | None = None,
    active_paths: set[str] | None = None,
    ffprobe_cmd: str = "ffprobe",
    media_jobs: dict[str, str] | None = None,
    include_in_progress: bool = False,
    inventory: bool = False,
) -> None:
    # Repair / external AV1 encodes write temp MP4s beside the source; never list those.
    if _is_transient_media_name(path.name):
        return
    entry = _media_entry(
        path,
        username,
        subdir=subdir,
        active_paths=active_paths,
        ffprobe_cmd=ffprobe_cmd,
        media_jobs=media_jobs,
        inventory=inventory,
    )
    if entry["in_progress"] and not include_in_progress:
        return
    entries.append(entry)


def _collect_user_media(
    user_dir: Path,
    username: str,
    *,
    active_paths: set[str] | None = None,
    ffprobe_cmd: str = "ffprobe",
    media_jobs: dict[str, str] | None = None,
    include_in_progress: bool = False,
    inventory: bool = False,
) -> list[dict]:
    entries: list[dict] = []
    for path in user_dir.glob("TK_*.mp4"):
        if path.is_file():
            _append_library_entry(
                entries,
                path,
                username,
                active_paths=active_paths,
                ffprobe_cmd=ffprobe_cmd,
                media_jobs=media_jobs,
                include_in_progress=include_in_progress,
                inventory=inventory,
            )
    legacy_dir = user_dir / LEGACY_SUBDIR
    if legacy_dir.is_dir():
        for path in legacy_dir.glob("*.mp4"):
            if path.is_file():
                _append_library_entry(
                    entries,
                    path,
                    username,
                    subdir=LEGACY_SUBDIR,
                    active_paths=active_paths,
                    ffprobe_cmd=ffprobe_cmd,
                    media_jobs=media_jobs,
                    include_in_progress=include_in_progress,
                    inventory=inventory,
                )
    return entries


def _iter_flv_paths(
    output_base: Path, custom_output: str | Path | None
) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    if custom_output is not None:
        root = Path(custom_output)
        if not root.is_dir():
            return found
        for path in root.glob("TK_*_flv.mp4"):
            if path.is_file():
                match = MEDIA_PATTERN.match(path.name)
                username = match.group("username") if match else "unknown"
                found.append((path, username))
        return found

    if not output_base.is_dir():
        return found
    for user_dir in sorted(output_base.iterdir()):
        if not user_dir.is_dir():
            continue
        for path in user_dir.glob("TK_*_flv.mp4"):
            if path.is_file():
                found.append((path, user_dir.name))
    return found


def is_active_recording_file(path: Path, active_output_paths: set[str] | None) -> bool:
    active_paths = _normalize_active_paths(active_output_paths)
    try:
        return str(path.resolve()) in active_paths
    except OSError:
        return str(path) in active_paths


def find_orphan_flv_files(
    output_base: Path,
    custom_output: str | Path | None,
    active_output_paths: set[str] | None = None,
) -> list[dict]:
    """Return leftover *_flv.mp4 files that are not active recordings."""
    active_paths = _normalize_active_paths(active_output_paths)
    orphans: list[dict] = []
    for path, username in _iter_flv_paths(output_base, custom_output):
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path)
        if resolved in active_paths:
            continue
        stat = path.stat()
        orphans.append(
            {
                "filename": path.name,
                "username": username,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
                "path": resolved,
            }
        )
    orphans.sort(key=lambda item: item["modified_at"], reverse=True)
    return orphans


def move_orphan_flv_files(
    output_base: Path,
    custom_output: str | Path | None,
    active_output_paths: set[str] | None,
    dest_dir: Path,
) -> dict:
    """Move leftover *_flv.mp4 files into dest_dir (flat, no username subdirs)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    active_paths = _normalize_active_paths(active_output_paths)
    orphans = find_orphan_flv_files(output_base, custom_output, active_paths)
    moved = 0
    failed = 0
    files: list[dict] = []
    for item in orphans:
        src = Path(item["path"])
        dest = dest_dir / item["filename"]
        try:
            resolved = str(src.resolve())
        except OSError:
            resolved = str(src)
        if resolved in active_paths:
            failed += 1
            files.append(
                {
                    "filename": item["filename"],
                    "username": item["username"],
                    "ok": False,
                    "error": "skipped (recording in progress)",
                }
            )
            continue
        if dest.exists():
            failed += 1
            files.append(
                {
                    "filename": item["filename"],
                    "username": item["username"],
                    "ok": False,
                    "error": "destination already exists",
                }
            )
            continue
        try:
            shutil.move(str(src), str(dest))
            moved += 1
            files.append(
                {
                    "filename": item["filename"],
                    "username": item["username"],
                    "ok": True,
                    "error": None,
                }
            )
        except OSError as exc:
            failed += 1
            files.append(
                {
                    "filename": item["filename"],
                    "username": item["username"],
                    "ok": False,
                    "error": str(exc),
                }
            )
    return {"moved": moved, "failed": failed, "files": files}


def _thumbnail_scan_dirs(
    output_base: Path, custom_output: str | Path | None
) -> list[Path]:
    """Directories that can hold ``*.thumb.jpg`` next to recordings."""
    if custom_output is not None:
        root = Path(custom_output)
        return [root] if root.is_dir() else []
    if not output_base.is_dir():
        return []
    dirs: list[Path] = []
    for user_dir in output_base.iterdir():
        if not user_dir.is_dir():
            continue
        dirs.append(user_dir)
        legacy_dir = user_dir / LEGACY_SUBDIR
        if legacy_dir.is_dir():
            dirs.append(legacy_dir)
    return dirs


def scan_media_library(
    output_base: Path,
    custom_output: str | Path | None,
    active_output_paths: set[str] | None = None,
    *,
    ffprobe_cmd: str = "ffprobe",
) -> dict[str, list[dict]]:
    """Return playable media grouped by username, newest first within each user."""
    configure_codec_index(output_base, custom_output)
    purge_orphan_thumbnails(_thumbnail_scan_dirs(output_base, custom_output))
    active_paths = _normalize_active_paths(active_output_paths)
    grouped: dict[str, list[dict]] = {}

    if custom_output is not None:
        root = Path(custom_output)
        if not root.is_dir():
            return grouped
        for path in root.glob("TK_*.mp4"):
            if not path.is_file():
                continue
            match = MEDIA_PATTERN.match(path.name)
            username = match.group("username") if match else "unknown"
            bucket = grouped.setdefault(username, [])
            _append_library_entry(
                bucket,
                path,
                username,
                active_paths=active_paths,
                ffprobe_cmd=ffprobe_cmd,
            )
    else:
        if not output_base.is_dir():
            return grouped
        for user_dir in sorted(output_base.iterdir()):
            if not user_dir.is_dir():
                continue
            entries = _collect_user_media(
                user_dir,
                user_dir.name,
                active_paths=active_paths,
                ffprobe_cmd=ffprobe_cmd,
            )
            if entries:
                grouped[user_dir.name] = entries

    for _username, entries in grouped.items():
        entries.sort(key=lambda item: item["modified_at"], reverse=True)

    get_codec_index().save()
    return dict(sorted(grouped.items(), key=lambda item: item[0].lower()))


def scan_media_inventory(
    output_base: Path,
    custom_output: str | Path | None,
    active_output_paths: set[str] | None = None,
    *,
    media_jobs: list[dict] | None = None,
    ffprobe_cmd: str = "ffprobe",
    ready: bool = False,
) -> list[dict]:
    """Return every library MP4 (including in-progress) with codec and busy flags."""
    configure_codec_index(output_base, custom_output)
    active_paths = _normalize_active_paths(active_output_paths)
    jobs = _job_status_map(media_jobs)
    videos: list[dict] = []
    live_paths: set[str] = set()

    if custom_output is not None:
        root = Path(custom_output)
        if root.is_dir():
            for path in root.glob("TK_*.mp4"):
                if not path.is_file():
                    continue
                match = MEDIA_PATTERN.match(path.name)
                username = match.group("username") if match else "unknown"
                before = len(videos)
                _append_library_entry(
                    videos,
                    path,
                    username,
                    active_paths=active_paths,
                    ffprobe_cmd=ffprobe_cmd,
                    media_jobs=jobs,
                    include_in_progress=True,
                    inventory=True,
                )
                if len(videos) > before:
                    live_paths.add(videos[-1]["path"])
    elif output_base.is_dir():
        for user_dir in sorted(output_base.iterdir()):
            if not user_dir.is_dir():
                continue
            entries = _collect_user_media(
                user_dir,
                user_dir.name,
                active_paths=active_paths,
                ffprobe_cmd=ffprobe_cmd,
                media_jobs=jobs,
                include_in_progress=True,
                inventory=True,
            )
            videos.extend(entries)
            live_paths.update(item["path"] for item in entries)

    index = get_codec_index()
    index.prune(live_paths)
    index.save(force=True)

    videos.sort(key=lambda item: item["modified_at"], reverse=True)
    if ready:
        videos = [item for item in videos if _is_inventory_ready(item)]
    return videos


def start_codec_warmup_worker(
    output_base: Path,
    custom_output: str | Path | None,
    ffprobe_cmd: str,
    stop_event: threading.Event,
    *,
    active_output_paths: set[str] | None = None,
) -> threading.Thread:
    """Background-probe codec-index misses so inventory HTTP stays a directory listing."""

    def _run() -> None:
        if stop_event.is_set():
            return
        try:
            configure_codec_index(output_base, custom_output)
            scan_media_inventory(
                output_base,
                custom_output,
                active_output_paths=active_output_paths,
                media_jobs=[],
                ffprobe_cmd=ffprobe_cmd,
                ready=False,
            )
        except Exception:
            logger.exception("Codec index warmup failed")

    thread = threading.Thread(
        target=_run,
        name="codec-index-warmup",
        daemon=True,
    )
    thread.start()
    return thread


def resolve_media_path(
    output_base: Path,
    custom_output: str | Path | None,
    username: str,
    filename: str,
    *,
    subdir: str | None = None,
) -> Path | None:
    if not _is_safe_filename(filename):
        return None
    if not _is_safe_username(username):
        return None
    if subdir == LEGACY_SUBDIR:
        if subdir in filename:
            return None
    elif not MEDIA_PATTERN.match(filename):
        return None

    if custom_output is not None:
        if subdir:
            return None
        candidate = Path(custom_output) / filename
        allowed_roots = [Path(custom_output).resolve()]
    else:
        user_root = output_base / username
        candidate = user_root / subdir / filename if subdir else user_root / filename
        allowed_roots = [
            (user_root / subdir).resolve() if subdir else user_root.resolve()
        ]

    try:
        resolved = candidate.resolve()
        allowed_roots = [root.resolve() for root in allowed_roots]
    except OSError:
        return None

    if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
        return None
    if not resolved.is_file():
        return None
    return resolved
