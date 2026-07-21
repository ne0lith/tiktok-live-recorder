from pathlib import Path

import requests

GITHUB_REPO = "ne0lith/tiktok-live-recorder"
GITHUB_BRANCH = "main"
GITHUB_RELEASES = f"https://github.com/{GITHUB_REPO}/releases"

URL_PYPROJECT = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/pyproject.toml"
)
FILE_TEMP_PYPROJECT = "pyproject_temp.toml"


def _download_file(url: str, file_name: str) -> bool:
    response = requests.get(url, stream=True, timeout=30)
    if response.status_code != 200:
        return False

    with open(file_name, "wb") as file:
        for chunk in response.iter_content(1024):
            file.write(chunk)
    return True


def _read_version_from_pyproject(path: str | Path) -> str:
    import tomllib

    with open(path, "rb") as f:
        return tomllib.load(f)["project"]["version"]


def _parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in str(version).split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_updates() -> bool:
    """
    Check if a newer version is available and print upgrade instructions.

    Returns:
        bool: Always False. Updates are notify-only; local files are not modified.
    """
    if not _download_file(URL_PYPROJECT, FILE_TEMP_PYPROJECT):
        try:
            Path(FILE_TEMP_PYPROJECT).unlink(missing_ok=True)
        except OSError:
            pass
        print("Unable to check for updates.")
        return False

    try:
        from utils.version import get_version

        remote_version = _read_version_from_pyproject(FILE_TEMP_PYPROJECT)
        local_version = get_version()

        if _parse_version(remote_version) <= _parse_version(local_version):
            return False

        print(f"Current version: {local_version}")
        print(f"New version available: {remote_version}")
        print("\nTo upgrade:")
        print("  git pull")
        print("  uv sync")
        print(f"\nOr download the latest release: {GITHUB_RELEASES}")
        return False
    finally:
        try:
            Path(FILE_TEMP_PYPROJECT).unlink(missing_ok=True)
        except OSError:
            pass
