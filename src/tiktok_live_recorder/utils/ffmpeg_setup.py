"""Resolve a capable FFmpeg binary (TikTok legacy HEVC-in-FLV / codec id 12)."""

from __future__ import annotations

import hashlib
import platform
import shutil
import struct
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from tiktok_live_recorder.utils.logger_manager import logger

BTBN_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
FFMPEG_PIN = "n8.1"
ARCH_ASSETS = {
    "linux64": f"ffmpeg-{FFMPEG_PIN}-latest-linux64-gpl-8.1.tar.xz",
    "linuxarm64": f"ffmpeg-{FFMPEG_PIN}-latest-linuxarm64-gpl-8.1.tar.xz",
}

FLV_CODECID_X_HEVC = 12
FLV_IS_EX_HEADER = 0x80
FLV_FRAME_KEY = 0x10


def find_repo_root() -> Path:
    """Locate project root (directory containing pyproject.toml)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def vendor_ffmpeg_dir(arch_key: str) -> Path:
    return find_repo_root() / ".vendor" / "ffmpeg" / f"{FFMPEG_PIN}-{arch_key}"


def ffprobe_for(ffmpeg_path: str) -> str:
    path = Path(ffmpeg_path)
    if path.name == "ffmpeg":
        candidate = path.with_name("ffprobe")
        if candidate.is_file():
            return str(candidate)
    return str(ffmpeg_path).replace("ffmpeg", "ffprobe")


def _linux_arch_key() -> str | None:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "linux64"
    if machine in ("aarch64", "arm64"):
        return "linuxarm64"
    return None


def build_legacy_hevc_probe_flv() -> bytes:
    """Minimal FLV with legacy codec-id-12 HEVC sequence header for capability tests."""
    # Tiny HVCC-like payload (invalid video, but enough for demuxer codec detection).
    hvcc = bytes(
        [
            0x01,
            0x01,
            0x60,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x96,
            0xF0,
            0x00,
            0xFC,
            0xFD,
            0xF8,
            0xF8,
            0x00,
            0x00,
            0x0F,
            0x03,
            0xE0,
            0x00,
            0x1E,
            0x07,
            0x80,
            0x00,
            0x00,
            0x03,
            0x00,
            0x80,
            0x00,
            0x00,
            0x1E,
            0x07,
            0x8C,
            0x18,
            0x80,
            0x01,
            0x00,
            0x04,
            0x28,
            0x01,
            0x0C,
            0x01,
            0xFF,
            0xFF,
            0x01,
            0x60,
            0x00,
            0x00,
            0x03,
            0x00,
            0x80,
            0x00,
            0x00,
            0x03,
            0x00,
            0x00,
            0x03,
            0x00,
            0x78,
            0x9D,
            0xC0,
            0x90,
        ]
    )
    video_body = bytes([FLV_FRAME_KEY | FLV_CODECID_X_HEVC, 0x00, 0, 0, 0]) + hvcc
    return _wrap_flv_video_tag(video_body)


def _wrap_flv_video_tag(video_body: bytes) -> bytes:
    header = b"FLV\x01\x01\x00\x00\x00\x09"
    prev_size = struct.pack(">I", 0)
    tag_type = 9
    data_size = len(video_body)
    timestamp = 0
    tag_header = bytes(
        [
            tag_type,
            (data_size >> 16) & 0xFF,
            (data_size >> 8) & 0xFF,
            data_size & 0xFF,
            (timestamp >> 16) & 0xFF,
            (timestamp >> 8) & 0xFF,
            timestamp & 0xFF,
            (timestamp >> 24) & 0xFF,
            0,
            0,
            0,
        ]
    )
    tag = tag_header + video_body
    tag_footer = struct.pack(">I", len(tag_header) + data_size)
    return header + prev_size + tag + tag_footer


def _ffprobe_legacy_hevc(flv_path: str, probe_cmd: str) -> bool:
    result = subprocess.run(
        [
            probe_cmd,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            flv_path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip().lower() == "hevc":
        return True
    combined = (result.stderr or "") + (result.stdout or "")
    if "Video codec (c) is not implemented" in combined:
        return False
    if "unknown codec" in combined.lower():
        return False
    return False


def _ffmpeg_inspect_legacy_hevc(flv_path: str, ffmpeg_cmd: str) -> bool:
    """Fallback probe: ffmpeg -i often reports HEVC when ffprobe cannot."""
    result = subprocess.run(
        [
            ffmpeg_cmd,
            "-hide_banner",
            "-nostats",
            "-i",
            flv_path,
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    combined = (result.stderr or "") + (result.stdout or "")
    lower = combined.lower()
    if "video codec (c) is not implemented" in lower:
        return False
    if "unknown codec" in lower:
        return False
    return "video: hevc" in lower


def ffmpeg_supports_legacy_hevc_flv(ffmpeg_path: str) -> bool:
    """Return True when ffmpeg can demux TikTok legacy FLV HEVC (codec id 12)."""
    if not shutil.which(ffmpeg_path) and not Path(ffmpeg_path).is_file():
        return False

    probe = ffprobe_for(ffmpeg_path)
    with tempfile.NamedTemporaryFile(suffix=".flv", delete=False) as tmp:
        tmp.write(build_legacy_hevc_probe_flv())
        tmp_path = tmp.name

    try:
        if _ffprobe_legacy_hevc(tmp_path, probe):
            return True
        return _ffmpeg_inspect_legacy_hevc(tmp_path, ffmpeg_path)
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def ffmpeg_version_line(ffmpeg_path: str) -> str:
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        first = (result.stdout or result.stderr or "").splitlines()
        return first[0] if first else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _parse_checksums(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            sums[parts[-1]] = parts[0].lower()
    return sums


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def _extract_ffmpeg_tree(archive: Path, dest_dir: Path) -> tuple[Path, Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="r:xz") as tar:
        tar.extractall(path=dest_dir, filter="data")

    ffmpeg_bins = sorted(dest_dir.rglob("ffmpeg"))
    ffprobe_bins = sorted(dest_dir.rglob("ffprobe"))
    ffmpeg_bin = next((p for p in ffmpeg_bins if p.is_file()), None)
    ffprobe_bin = next((p for p in ffprobe_bins if p.is_file()), None)
    if ffmpeg_bin is None or ffprobe_bin is None:
        raise RuntimeError(f"ffmpeg/ffprobe not found after extracting {archive.name}")

    install_root = dest_dir / "bin"
    install_root.mkdir(parents=True, exist_ok=True)
    target_ffmpeg = install_root / "ffmpeg"
    target_ffprobe = install_root / "ffprobe"
    shutil.copy2(ffmpeg_bin, target_ffmpeg)
    shutil.copy2(ffprobe_bin, target_ffprobe)
    target_ffmpeg.chmod(0o755)
    target_ffprobe.chmod(0o755)
    return target_ffmpeg, target_ffprobe


def install_linux_vendor_ffmpeg(arch_key: str) -> str:
    asset = ARCH_ASSETS[arch_key]
    install_dir = vendor_ffmpeg_dir(arch_key)
    target_ffmpeg = install_dir / "bin" / "ffmpeg"
    if target_ffmpeg.is_file() and ffmpeg_supports_legacy_hevc_flv(str(target_ffmpeg)):
        return str(target_ffmpeg)

    if install_dir.exists():
        shutil.rmtree(install_dir, ignore_errors=True)

    archive_url = f"{BTBN_BASE}/{asset}"
    checksums_url = f"{BTBN_BASE}/checksums.sha256"
    logger.info(f"Downloading capable FFmpeg ({asset}) for TikTok HEVC FLV...")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / asset
        _download(archive_url, archive_path)

        checksums_text = requests.get(checksums_url, timeout=60).text
        expected = _parse_checksums(checksums_text).get(asset)
        if expected:
            actual = _sha256_file(archive_path)
            if actual != expected:
                raise RuntimeError(
                    f"Checksum mismatch for {asset} (expected {expected}, got {actual})"
                )
        else:
            logger.warning(f"No checksum entry for {asset}; skipping SHA-256 verify")

        ffmpeg_bin, _ffprobe_bin = _extract_ffmpeg_tree(archive_path, install_dir)
        if not ffmpeg_supports_legacy_hevc_flv(str(ffmpeg_bin)):
            raise RuntimeError(
                f"Installed FFmpeg at {ffmpeg_bin} still cannot demux legacy HEVC FLV"
            )
        logger.info(f"Installed capable FFmpeg: {ffmpeg_bin}")
        return str(ffmpeg_bin)


def normalize_cdn_url(url: str) -> str:
    """Identity for CDN URLs ignoring signed query parameters."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def resolve_ffmpeg_path(ffmpeg_path: str | None = None) -> str:
    """
    Return an ffmpeg binary that can demux TikTok legacy HEVC FLV when possible.

    Order: explicit path (if capable) → PATH ffmpeg → Linux vendor install.
    On Linux with no ffmpeg installed, downloads BtbN n8.1 into .vendor/ffmpeg/.
    """
    candidates: list[str] = []
    if ffmpeg_path:
        resolved = shutil.which(ffmpeg_path) or str(Path(ffmpeg_path))
        candidates.append(resolved)
    else:
        path_ffmpeg = shutil.which("ffmpeg")
        if path_ffmpeg:
            candidates.append(path_ffmpeg)

    for candidate in candidates:
        if ffmpeg_supports_legacy_hevc_flv(candidate):
            return candidate

    if platform.system().lower() == "linux":
        arch_key = _linux_arch_key()
        if arch_key is None:
            raise RuntimeError(
                f"Unsupported Linux architecture for bundled FFmpeg: {platform.machine()}"
            )
        try:
            return install_linux_vendor_ffmpeg(arch_key)
        except Exception as exc:
            logger.warning(
                f"Could not install vendor FFmpeg ({exc}); "
                "HEVC FLV conversion may need the tag rewriter fallback."
            )

    if candidates:
        logger.warning(
            f"FFmpeg at {candidates[0]} cannot demux TikTok legacy HEVC FLV "
            f"({ffmpeg_version_line(candidates[0])}). "
            "Install FFmpeg 8.0+ or allow automatic vendor install on Linux."
        )
        return candidates[0]

    raise FileNotFoundError("FFmpeg binary not found")


def log_ffmpeg_status(ffmpeg_path: str) -> None:
    info = describe_ffmpeg_binary(ffmpeg_path)
    status = (
        "capable for TikTok HEVC FLV"
        if info["hevc_capable"]
        else "NOT capable for TikTok HEVC FLV"
    )
    logger.info(f"FFmpeg: {info['path']} ({info['version']}) — {status}")


def describe_ffmpeg_binary(ffmpeg_path: str | None) -> dict[str, Any]:
    """Return resolved FFmpeg path, install source, version, and HEVC capability."""
    if not ffmpeg_path:
        return {
            "path": None,
            "source": "missing",
            "version": None,
            "hevc_capable": False,
        }

    path = Path(ffmpeg_path)
    try:
        resolved = str(path.resolve()) if path.is_file() else ffmpeg_path
    except OSError:
        resolved = ffmpeg_path

    source = "custom"
    try:
        resolved_path = Path(resolved)
        parts = resolved_path.parts
        if ".vendor" in parts and "ffmpeg" in parts:
            source = "vendor"
        else:
            system_ffmpeg = shutil.which("ffmpeg")
            if (
                system_ffmpeg
                and resolved_path.resolve() == Path(system_ffmpeg).resolve()
            ):
                source = "system"
    except OSError:
        pass

    exists = path.is_file() or bool(shutil.which(ffmpeg_path))
    capable = ffmpeg_supports_legacy_hevc_flv(ffmpeg_path) if exists else False

    return {
        "path": resolved,
        "source": source,
        "version": ffmpeg_version_line(ffmpeg_path) if exists else None,
        "hevc_capable": capable,
    }
