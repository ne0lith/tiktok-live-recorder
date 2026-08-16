"""Persistent codec index so library scans do not ffprobe every file on each request."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from tiktok_live_recorder.utils.video_management import VideoManagement

INDEX_FILENAME = ".media-codec-index.json"
INDEX_VERSION = 1
_FLUSH_EVERY = 25

_index_guard = threading.Lock()
_index: CodecIndex | None = None
_index_path: Path | None = None


class CodecIndex:
    """path + mtime_ns + size → (codec, pix_fmt), plus stems that currently have .av1temp."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._av1temp_stems: set[str] = set()
        self._dirty = False
        self._unsaved_probes = 0
        if self.path is not None:
            self.load()

    def load(self) -> None:
        if self.path is None or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(raw, dict) or raw.get("version") != INDEX_VERSION:
            return
        entries = raw.get("entries") or {}
        stems = raw.get("av1temp_stems") or []
        loaded: dict[str, dict[str, Any]] = {}
        if isinstance(entries, dict):
            for key, value in entries.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                try:
                    loaded[key] = {
                        "mtime_ns": int(value["mtime_ns"]),
                        "size": int(value["size"]),
                        "codec": str(value.get("codec") or ""),
                        "pix_fmt": str(value.get("pix_fmt") or ""),
                    }
                except (KeyError, TypeError, ValueError):
                    continue
        with self._lock:
            self._entries = loaded
            self._av1temp_stems = {str(item) for item in stems if item}
            self._dirty = False
            self._unsaved_probes = 0

    def save(self, *, force: bool = False) -> None:
        with self._lock:
            if force or self._dirty:
                self._save_unlocked()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._av1temp_stems.clear()
            self._dirty = True
            self._unsaved_probes = 0

    def lookup(self, resolved: str, mtime_ns: int, size: int) -> tuple[str, str] | None:
        with self._lock:
            return self._lookup_unlocked(resolved, mtime_ns, size)

    def note_av1temp(self, resolved: str, has_temp: bool) -> bool:
        """Track sibling ``.av1temp.mp4``. Return True when it just disappeared."""
        with self._lock:
            was = resolved in self._av1temp_stems
            if has_temp:
                if not was:
                    self._av1temp_stems.add(resolved)
                    self._dirty = True
                return False
            if was:
                self._av1temp_stems.discard(resolved)
                self._dirty = True
                return True
            return False

    def get_or_probe(
        self,
        path: Path,
        ffprobe_cmd: str,
        *,
        skip_probe: bool = False,
        force: bool = False,
    ) -> tuple[str, str]:
        try:
            st = path.stat()
            resolved = str(path.resolve())
        except OSError:
            return "", ""
        if st.st_size <= 0:
            return "", ""
        with self._lock:
            if not force:
                hit = self._lookup_unlocked(resolved, st.st_mtime_ns, st.st_size)
                if hit is not None:
                    return hit
            if skip_probe:
                return "", ""
        codec, pix_fmt = VideoManagement._probe_video_info(str(path), ffprobe_cmd)
        with self._lock:
            self._entries[resolved] = {
                "mtime_ns": st.st_mtime_ns,
                "size": st.st_size,
                "codec": codec,
                "pix_fmt": pix_fmt,
            }
            self._dirty = True
            self._unsaved_probes += 1
            if self._unsaved_probes >= _FLUSH_EVERY:
                self._save_unlocked()
        return codec, pix_fmt

    def prune(self, live_paths: set[str]) -> None:
        with self._lock:
            stale = [key for key in self._entries if key not in live_paths]
            stale_stems = [key for key in self._av1temp_stems if key not in live_paths]
            if not stale and not stale_stems:
                return
            for key in stale:
                del self._entries[key]
            for key in stale_stems:
                self._av1temp_stems.discard(key)
            self._dirty = True

    def _lookup_unlocked(
        self, resolved: str, mtime_ns: int, size: int
    ) -> tuple[str, str] | None:
        entry = self._entries.get(resolved)
        if entry is None:
            return None
        if entry.get("mtime_ns") != mtime_ns or entry.get("size") != size:
            return None
        return str(entry.get("codec") or ""), str(entry.get("pix_fmt") or "")

    def _save_unlocked(self) -> None:
        if self.path is None:
            self._dirty = False
            self._unsaved_probes = 0
            return
        payload = {
            "version": INDEX_VERSION,
            "entries": dict(self._entries),
            "av1temp_stems": sorted(self._av1temp_stems),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(payload, indent=0), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            return
        self._dirty = False
        self._unsaved_probes = 0


def codec_index_path(output_base: Path, custom_output: str | Path | None) -> Path:
    root = Path(custom_output) if custom_output is not None else Path(output_base)
    return root / INDEX_FILENAME


def configure_codec_index(
    output_base: Path, custom_output: str | Path | None
) -> CodecIndex:
    """Load (or switch to) the index file for this output root."""
    global _index, _index_path
    path = codec_index_path(output_base, custom_output)
    with _index_guard:
        if _index is not None and _index_path == path:
            return _index
        if _index is not None:
            _index.save(force=True)
        _index_path = path
        _index = CodecIndex(path)
        return _index


def get_codec_index() -> CodecIndex:
    global _index
    with _index_guard:
        if _index is None:
            _index = CodecIndex(None)
        return _index


def reset_codec_index() -> None:
    """Drop the process-wide index (tests). Does not delete on-disk files."""
    global _index, _index_path
    with _index_guard:
        _index = None
        _index_path = None
