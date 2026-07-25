import re
from pathlib import Path

MEDIA_PATTERN = re.compile(r"^TK_(?P<username>[^_]+)_.*\.mp4$", re.IGNORECASE)
LEGACY_SUBDIR = "legacy"


def _is_safe_filename(filename: str) -> bool:
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    return filename.lower().endswith(".mp4")


def _media_entry(path: Path, username: str, *, subdir: str | None = None) -> dict:
    stat = path.stat()
    if subdir:
        url = f"/media/{username}/{subdir}/{path.name}"
    else:
        url = f"/media/{username}/{path.name}"
    return {
        "filename": path.name,
        "username": username,
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "in_progress": path.name.endswith("_flv.mp4"),
        "source": subdir or "recordings",
        "url": url,
    }


def _collect_user_media(user_dir: Path, username: str) -> list[dict]:
    entries: list[dict] = []
    for path in user_dir.glob("TK_*.mp4"):
        if path.is_file():
            entries.append(_media_entry(path, username))
    legacy_dir = user_dir / LEGACY_SUBDIR
    if legacy_dir.is_dir():
        for path in legacy_dir.glob("*.mp4"):
            if path.is_file():
                entries.append(_media_entry(path, username, subdir=LEGACY_SUBDIR))
    return entries


def scan_media_library(
    output_base: Path, custom_output: str | Path | None
) -> dict[str, list[dict]]:
    """Return playable media grouped by username, newest first within each user."""
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
            grouped.setdefault(username, []).append(_media_entry(path, username))
    else:
        if not output_base.is_dir():
            return grouped
        for user_dir in sorted(output_base.iterdir()):
            if not user_dir.is_dir():
                continue
            entries = _collect_user_media(user_dir, user_dir.name)
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
