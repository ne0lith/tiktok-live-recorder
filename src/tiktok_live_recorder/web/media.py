import re
from pathlib import Path

from tiktok_live_recorder.web.thumbnails import thumbnail_url

MEDIA_PATTERN = re.compile(r"^TK_(?P<username>[^_]+)_.*\.mp4$", re.IGNORECASE)
LEGACY_SUBDIR = "legacy"


def _is_safe_filename(filename: str) -> bool:
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    return filename.lower().endswith(".mp4")


def _normalize_active_paths(active_output_paths: set[str] | None) -> set[str]:
    normalized: set[str] = set()
    for path in active_output_paths or ():
        try:
            normalized.add(str(Path(path).resolve()))
        except OSError:
            normalized.add(str(path))
    return normalized


def _media_entry(
    path: Path,
    username: str,
    *,
    subdir: str | None = None,
    active_paths: set[str] | None = None,
) -> dict:
    stat = path.stat()
    if subdir:
        url = f"/media/{username}/{subdir}/{path.name}"
    else:
        url = f"/media/{username}/{path.name}"
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    is_flv = path.name.endswith("_flv.mp4")
    is_active = resolved in (active_paths or set())
    entry = {
        "filename": path.name,
        "username": username,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "in_progress": is_flv and is_active,
        "needs_convert": is_flv and not is_active,
        "source": subdir or "recordings",
        "url": url,
        "path": resolved,
    }
    if not entry["in_progress"] and not is_flv:
        entry["thumb_url"] = thumbnail_url(username, path.name, subdir=subdir)
    return entry


def _append_library_entry(
    entries: list[dict],
    path: Path,
    username: str,
    *,
    subdir: str | None = None,
    active_paths: set[str] | None = None,
) -> None:
    entry = _media_entry(path, username, subdir=subdir, active_paths=active_paths)
    if entry["in_progress"]:
        return
    entries.append(entry)


def _collect_user_media(
    user_dir: Path, username: str, *, active_paths: set[str] | None = None
) -> list[dict]:
    entries: list[dict] = []
    for path in user_dir.glob("TK_*.mp4"):
        if path.is_file():
            _append_library_entry(entries, path, username, active_paths=active_paths)
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


def scan_media_library(
    output_base: Path,
    custom_output: str | Path | None,
    active_output_paths: set[str] | None = None,
) -> dict[str, list[dict]]:
    """Return playable media grouped by username, newest first within each user."""
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
            _append_library_entry(bucket, path, username, active_paths=active_paths)
    else:
        if not output_base.is_dir():
            return grouped
        for user_dir in sorted(output_base.iterdir()):
            if not user_dir.is_dir():
                continue
            entries = _collect_user_media(
                user_dir, user_dir.name, active_paths=active_paths
            )
            if entries:
                grouped[user_dir.name] = entries

    for _username, entries in grouped.items():
        entries.sort(key=lambda item: item["modified_at"], reverse=True)

    return dict(sorted(grouped.items(), key=lambda item: item[0].lower()))


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
