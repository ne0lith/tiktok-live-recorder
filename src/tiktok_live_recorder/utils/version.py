from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return package version. Source of truth: [project] version in pyproject.toml."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("tiktok-live-recorder")
    except PackageNotFoundError:
        pass

    import tomllib

    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file():
            with pyproject.open("rb") as f:
                return tomllib.load(f)["project"]["version"]

    raise FileNotFoundError("pyproject.toml not found")


def banner_text() -> str:
    version = get_version()
    return rf"""

  _____ _ _   _____    _     _    _           ___                   _         
 |_   _|(_) |_|_   _|__| |__ | |  (_)_ _____  | _ \___ __ ___ _ _ __| |___ _ _ 
   | | | | / / | |/ _ \ / / | |__| \ V / -_) |   / -_) _/ _ \ '_/ _` / -_) '_|
   |_| |_|_\_\ |_|\___/_\_\ |____|_|\_/\___| |_|_\___\__\___/_| \__,_\___|_| 

   V{version}
"""
