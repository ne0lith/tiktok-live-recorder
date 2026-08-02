from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def _pyproject_path() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file():
            return pyproject
    return None


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return installed package version (loaded at process start)."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("tiktok-live-recorder")
    except PackageNotFoundError:
        pass
    return get_repo_version()


@lru_cache(maxsize=1)
def get_repo_version() -> str:
    """Return version from on-disk pyproject.toml (may differ after hot update)."""
    import tomllib

    pyproject = _pyproject_path()
    if pyproject is None:
        raise FileNotFoundError("pyproject.toml not found")
    with pyproject.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def banner_text() -> str:
    version = get_version()
    return rf"""

  _____ _ _   _____    _     _    _           ___                   _         
 |_   _|(_) |_|_   _|__| |__ | |  (_)_ _____  | _ \___ __ ___ _ _ __| |___ _ _ 
   | | | | / / | |/ _ \ / / | |__| \ V / -_) |   / -_) _/ _ \ '_/ _` / -_) '_|
   |_| |_|_\_\ |_|\___/_\_\ |____|_|\_/\___| |_|_\___\__\___/_| \__,_\___|_| 

   V{version}
"""
