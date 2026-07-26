from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

LOG_LEVEL_PATTERN = re.compile(r" \[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\] ")
LEVEL_RANK = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def _line_level(line: str) -> str | None:
    match = LOG_LEVEL_PATTERN.search(line)
    return match.group(1) if match else None


def _filter_lines(lines: list[str], min_level: str) -> list[str]:
    threshold = LEVEL_RANK[min_level]
    filtered: list[str] = []
    keep_next = False
    for line in lines:
        level = _line_level(line)
        if level is not None:
            keep_next = LEVEL_RANK[level] >= threshold
        if keep_next:
            filtered.append(line)
    return filtered


def read_log_tail(
    path: Path,
    *,
    max_lines: int = 300,
    max_bytes: int = 512_000,
    min_level: str | None = None,
) -> dict[str, Any]:
    """Return the last lines from the recorder log file."""
    if max_lines < 1:
        raise ValueError("max_lines must be at least 1")
    if min_level is not None and min_level not in LEVEL_RANK:
        raise ValueError(f"Unsupported log level: {min_level}")

    if not path.is_file():
        return {
            "path": str(path.resolve()),
            "lines": [],
            "truncated": False,
            "size": 0,
        }

    size = path.stat().st_size
    truncated = False
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            raw = handle.read()
            if b"\n" in raw:
                raw = raw.split(b"\n", 1)[1]
            truncated = True
        else:
            raw = handle.read()

    all_lines = raw.decode("utf-8", errors="replace").splitlines()
    if min_level is not None:
        all_lines = _filter_lines(all_lines, min_level)

    if len(all_lines) > max_lines:
        truncated = True
        lines = all_lines[-max_lines:]
    else:
        lines = all_lines

    return {
        "path": str(path.resolve()),
        "lines": lines,
        "truncated": truncated,
        "size": size,
    }
