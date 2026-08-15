"""Git-based in-app updates for git clone + uv installs."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests

GITHUB_REPO = "ne0lith/tiktok-live-recorder"
GITHUB_BRANCH = "main"
GITHUB_RELEASES = f"https://github.com/{GITHUB_REPO}/releases"
URL_PYPROJECT = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/pyproject.toml"
)

STATIC_WEB_PREFIX = "src/tiktok_live_recorder/web/static/"
SRC_PACKAGE_PREFIX = "src/tiktok_live_recorder/"

UpdateScope = Literal["hot", "restart"]


@dataclass
class UpdatePreview:
    current_version: str
    latest_version: str
    update_available: bool
    scope: UpdateScope | None
    changed_files: list[str]
    release_notes_url: str = GITHUB_RELEASES


@dataclass
class ApplyResult:
    scope: UpdateScope
    changed_files: list[str]
    static_changed: bool
    synced_dependencies: bool
    message: str


class UpdateError(Exception):
    """Update operation failed."""


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in str(version).split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def compare_versions(left: str, right: str) -> int:
    """Return -1 if left < right, 0 if equal, 1 if left > right."""
    a = _parse_version(left)
    b = _parse_version(right)
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def read_version_from_pyproject(path: str | Path) -> str:
    import tomllib

    with open(path, "rb") as f:
        return tomllib.load(f)["project"]["version"]


def find_repo_root(start: Path | None = None) -> Path | None:
    """Return git repo root containing pyproject.toml, or None."""
    if start is None:
        start = Path(__file__).resolve()
    path = start if start.is_dir() else start.parent
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists() and (candidate / "pyproject.toml").is_file():
            return candidate
    return None


def _command_available(name: str) -> bool:
    return shutil.which(name) is not None


def running_in_docker() -> bool:
    """True when running inside a container (in-app git updates must not run)."""
    if os.environ.get("TIKTOK_RECORDER_IN_DOCKER", "").strip() in {"1", "true", "yes"}:
        return True
    return Path("/.dockerenv").is_file()


def is_updatable_install(repo_root: Path | None = None) -> bool:
    """Git clone + git/uv, writable, and not Docker.

    Docker images are immutable; rebuild/pull a new image instead of git pull.
    """
    if running_in_docker():
        return False
    root = repo_root or find_repo_root()
    if root is None:
        return False
    if not _command_available("git") or not _command_available("uv"):
        return False
    try:
        return os.access(root, os.W_OK)
    except OSError:
        return False


def _run_git(
    repo_root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=check,
    )


def _upstream_ref(repo_root: Path) -> str:
    result = _run_git(
        repo_root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return f"origin/{GITHUB_BRANCH}"


def fetch_remote_version() -> str | None:
    try:
        response = requests.get(URL_PYPROJECT, timeout=30)
        if response.status_code != 200:
            return None
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".toml") as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name
        try:
            return read_version_from_pyproject(tmp_path)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except (OSError, requests.RequestException):
        return None


def classify_changed_files(paths: list[str]) -> UpdateScope:
    """Hot unless any non-static Python under src/tiktok_live_recorder changed."""
    for path in paths:
        normalized = path.replace("\\", "/")
        if not normalized.endswith(".py"):
            continue
        if not normalized.startswith(SRC_PACKAGE_PREFIX):
            continue
        if normalized.startswith(STATIC_WEB_PREFIX):
            continue
        return "restart"
    return "hot"


def _static_files_changed(paths: list[str]) -> bool:
    for path in paths:
        normalized = path.replace("\\", "/")
        if normalized.startswith(STATIC_WEB_PREFIX):
            return True
    return False


def _dependency_files_changed(paths: list[str]) -> bool:
    normalized = {path.replace("\\", "/") for path in paths}
    return "pyproject.toml" in normalized or "uv.lock" in normalized


def _git_changed_files(repo_root: Path, rev_range: str) -> list[str]:
    result = _run_git(repo_root, "diff", "--name-only", rev_range, check=False)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def preview_update_scope(repo_root: Path | None = None) -> UpdatePreview:
    from tiktok_live_recorder.utils.version import get_version

    root = repo_root or find_repo_root()
    current = get_version()
    latest = fetch_remote_version() or current
    update_available = compare_versions(current, latest) < 0

    changed_files: list[str] = []
    scope: UpdateScope | None = None

    if root is not None and is_updatable_install(root):
        fetch_result = _run_git(root, "fetch", check=False)
        if fetch_result.returncode == 0:
            upstream = _upstream_ref(root)
            changed_files = _git_changed_files(root, f"HEAD..{upstream}")
            if changed_files:
                scope = classify_changed_files(changed_files)

    return UpdatePreview(
        current_version=current,
        latest_version=latest,
        update_available=update_available,
        scope=scope,
        changed_files=changed_files,
        release_notes_url=GITHUB_RELEASES,
    )


def git_pull(repo_root: Path) -> list[str]:
    before = _run_git(repo_root, "rev-parse", "HEAD", check=False)
    old_head = before.stdout.strip() if before.returncode == 0 else ""

    result = _run_git(repo_root, "pull", "--ff-only", check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git pull failed").strip()
        raise UpdateError(detail)

    if old_head:
        return _git_changed_files(repo_root, f"{old_head}..HEAD")
    return _git_changed_files(repo_root, "HEAD@{1}..HEAD")


def uv_sync(repo_root: Path) -> None:
    result = subprocess.run(
        ["uv", "sync", "--frozen"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["uv", "sync"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "uv sync failed").strip()
        raise UpdateError(detail)


def apply_hot_update(repo_root: Path | None = None) -> ApplyResult:
    root = repo_root or find_repo_root()
    if root is None or not is_updatable_install(root):
        raise UpdateError("In-app updates require a git clone install with git and uv.")

    changed_files = git_pull(root)
    scope = classify_changed_files(changed_files)
    if scope == "restart":
        raise UpdateError(
            "Update requires a restart because backend Python files changed."
        )

    synced = False
    if _dependency_files_changed(changed_files):
        uv_sync(root)
        synced = True

    static_changed = _static_files_changed(changed_files)
    message = "Update applied."
    if static_changed:
        message = "Dashboard updated. Reload the page to see changes."
    elif synced:
        message = (
            "Release files updated on disk. Restart later to load new dependencies."
        )

    return ApplyResult(
        scope="hot",
        changed_files=changed_files,
        static_changed=static_changed,
        synced_dependencies=synced,
        message=message,
    )


def apply_restart_update_files(repo_root: Path) -> ApplyResult:
    """Pull and sync after graceful shutdown; caller relaunches process."""
    changed_files = git_pull(repo_root)
    uv_sync(repo_root)
    return ApplyResult(
        scope="restart",
        changed_files=changed_files,
        static_changed=_static_files_changed(changed_files),
        synced_dependencies=True,
        message="Files updated; restarting.",
    )


def relaunch(argv: list[str] | None = None) -> None:
    """Replace or spawn a new recorder process with the same CLI arguments."""
    args = argv if argv is not None else sys.argv[1:]
    executable = sys.executable
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        cmd = [executable, "-m", "tiktok_live_recorder", *args]
        subprocess.Popen(
            cmd,
            cwd=find_repo_root(),
            creationflags=creationflags,
            close_fds=True,
        )
        return

    os.execv(executable, [executable, "-m", "tiktok_live_recorder", *args])
