"""Resolve a capable FFmpeg binary (TikTok legacy HEVC-in-FLV / codec id 12)."""

from __future__ import annotations

import hashlib
import json
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

from tiktok_live_recorder.utils.flv_hevc_rewrite import rewrite_legacy_hevc_video_body
from tiktok_live_recorder.utils.logger_manager import logger
from tiktok_live_recorder.utils.custom_exceptions import FfmpegRequirementError

BTBN_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
FFMPEG_PIN = "n8.1"
ARCH_ASSETS = {
    "linux64": f"ffmpeg-{FFMPEG_PIN}-latest-linux64-gpl-8.1.tar.xz",
    "linuxarm64": f"ffmpeg-{FFMPEG_PIN}-latest-linuxarm64-gpl-8.1.tar.xz",
}

FLV_CODECID_X_HEVC = 12
FLV_IS_EX_HEADER = 0x80
FLV_FRAME_KEY = 0x10

_startup_ffmpeg_info: dict[str, Any] | None = None


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
    """Resolve ffprobe next to ffmpeg (basename only — never replace path segments)."""
    path = Path(ffmpeg_path)
    name = path.name
    if name.startswith("ffmpeg"):
        probe_name = f"ffprobe{name[len('ffmpeg') :]}"
        candidate = path.with_name(probe_name)
        if candidate.is_file():
            return str(candidate)
    which_probe = shutil.which("ffprobe")
    if which_probe:
        return which_probe
    return "ffprobe"


def _linux_arch_key() -> str | None:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "linux64"
    if machine in ("aarch64", "arm64"):
        return "linuxarm64"
    return None


def _legacy_hevc_sequence_body() -> bytes:
    """Video tag body: legacy FLV codec id 12 + HVCC-like sequence header."""
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
    return bytes([FLV_FRAME_KEY | FLV_CODECID_X_HEVC, 0x00, 0, 0, 0]) + hvcc


def build_legacy_hevc_probe_flv() -> bytes:
    """Minimal FLV with legacy codec-id-12 HEVC sequence header for capability tests."""
    return _wrap_flv_video_tag(_legacy_hevc_sequence_body())


def build_enhanced_hevc_probe_flv() -> bytes:
    """FLV after legacy codec-12 -> Enhanced hvc1 rewrite (salvage conversion path)."""
    body = rewrite_legacy_hevc_video_body(_legacy_hevc_sequence_body())
    return _wrap_flv_video_tag(body)


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
            "-nostdin",
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
            "-nostdin",
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
    if (
        "invalid data found when processing input" in lower
        and "video: hevc" not in lower
    ):
        return False
    return "video: hevc" in lower


def _binary_runs(binary_path: str) -> bool:
    path = Path(binary_path)
    if not path.is_file() and not shutil.which(binary_path):
        return False
    try:
        result = subprocess.run(
            [binary_path, "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ffmpeg_install_sane(ffmpeg_path: str) -> bool:
    """ffmpeg and paired ffprobe must exist and execute."""
    if not _binary_runs(ffmpeg_path):
        return False
    return _binary_runs(ffprobe_for(ffmpeg_path))


def _demux_flv_file_detects_hevc(flv_path: str, ffmpeg_path: str) -> bool:
    probe = ffprobe_for(ffmpeg_path)
    if _ffprobe_legacy_hevc(flv_path, probe):
        return True
    return _ffmpeg_inspect_legacy_hevc(flv_path, ffmpeg_path)


def _verify_ffmpeg_hevc_roundtrip(ffmpeg_path: str) -> bool:
    """
    Encode a 1-frame HEVC FLV with the binary under test, then demux it.

    This is a functional check that the installed build can read/write HEVC in FLV
    (the salvage conversion path), unlike static synthetic codec-12 fixtures.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        flv_path = Path(tmp_dir) / "hevc_roundtrip.flv"
        encode = subprocess.run(
            [
                ffmpeg_path,
                "-y",
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=64x64:d=0.1:r=1",
                "-frames:v",
                "1",
                "-c:v",
                "libx265",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-f",
                "flv",
                str(flv_path),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        if encode.returncode != 0:
            logger.debug(
                "HEVC FLV roundtrip encode failed for %s: %s",
                ffmpeg_path,
                (encode.stderr or encode.stdout or "").strip(),
            )
            return False
        if not flv_path.is_file() or flv_path.stat().st_size == 0:
            return False
        return _demux_flv_file_detects_hevc(str(flv_path), ffmpeg_path)


def _empty_hevc_probe() -> dict[str, bool]:
    return {"legacy": False, "enhanced": False, "roundtrip": False}


def _tiktok_hevc_capable_from_probes(probes: dict[str, bool]) -> bool:
    """TikTok salvage needs legacy codec-12 or Enhanced hvc1 demux, not libx265 roundtrip alone."""
    return probes["legacy"] or probes["enhanced"]


def verify_installed_ffmpeg(ffmpeg_path: str) -> tuple[bool, dict[str, bool]]:
    """Verify ffmpeg/ffprobe run and probe HEVC-in-FLV (TikTok + roundtrip sanity)."""
    probes = _empty_hevc_probe()
    if not _ffmpeg_install_sane(ffmpeg_path):
        return False, probes
    probes["legacy"] = _probe_flv_bytes(ffmpeg_path, build_legacy_hevc_probe_flv())
    probes["enhanced"] = _probe_flv_bytes(ffmpeg_path, build_enhanced_hevc_probe_flv())
    probes["roundtrip"] = _verify_ffmpeg_hevc_roundtrip(ffmpeg_path)
    capable = _tiktok_hevc_capable_from_probes(probes)
    return capable, probes


def _probe_flv_bytes(ffmpeg_path: str, flv_bytes: bytes) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".flv", delete=False) as tmp:
        tmp.write(flv_bytes)
        tmp_path = tmp.name

    try:
        return _demux_flv_file_detects_hevc(tmp_path, ffmpeg_path)
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def probe_ffmpeg_hevc_flv(ffmpeg_path: str) -> dict[str, bool]:
    """Run HEVC-in-FLV verification probes (synthetic fixtures + encode roundtrip)."""
    _, probes = verify_installed_ffmpeg(ffmpeg_path)
    return probes


def ffmpeg_supports_legacy_hevc_flv(ffmpeg_path: str) -> bool:
    """Return True when ffmpeg can demux the legacy codec-id-12 probe FLV."""
    if not shutil.which(ffmpeg_path) and not Path(ffmpeg_path).is_file():
        return False
    if not _ffmpeg_install_sane(ffmpeg_path):
        return False
    return _probe_flv_bytes(ffmpeg_path, build_legacy_hevc_probe_flv())


def ffmpeg_hevc_capable(ffmpeg_path: str) -> bool:
    """Return True when ffmpeg can demux TikTok legacy/enhanced HEVC-in-FLV probes."""
    if not shutil.which(ffmpeg_path) and not Path(ffmpeg_path).is_file():
        return False
    capable, _ = verify_installed_ffmpeg(ffmpeg_path)
    return capable


def ffmpeg_tiktok_hevc_capable(ffmpeg_path: str) -> bool:
    """Alias for ffmpeg_hevc_capable (legacy or enhanced probe must pass)."""
    return ffmpeg_hevc_capable(ffmpeg_path)


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


def is_vendor_ffmpeg_path(ffmpeg_path: str) -> bool:
    try:
        parts = Path(ffmpeg_path).resolve().parts
    except OSError:
        parts = Path(ffmpeg_path).parts
    if ".vendor" not in parts or "ffmpeg" not in parts:
        return False
    return any(part.startswith(f"{FFMPEG_PIN}-") for part in parts)


def _vendor_arch_for_path(ffmpeg_path: str) -> str | None:
    try:
        resolved = Path(ffmpeg_path).resolve()
    except OSError:
        resolved = Path(ffmpeg_path)
    for arch_key in ARCH_ASSETS:
        install_dir = vendor_ffmpeg_dir(arch_key)
        try:
            resolved.relative_to(install_dir)
            return arch_key
        except ValueError:
            continue
    return None


def _vendor_probe_marker(arch_key: str) -> Path:
    return vendor_ffmpeg_dir(arch_key) / ".hevc-probes.json"


def _load_vendor_probes(arch_key: str) -> dict[str, bool] | None:
    marker = _vendor_probe_marker(arch_key)
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        return {
            "legacy": bool(data["legacy"]),
            "enhanced": bool(data["enhanced"]),
            "roundtrip": bool(data.get("roundtrip", False)),
        }
    except (json.JSONDecodeError, KeyError, TypeError, OSError):
        return None


def _save_vendor_probes(arch_key: str, probes: dict[str, bool]) -> None:
    marker = _vendor_probe_marker(arch_key)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(probes), encoding="utf-8")


def _trusted_vendor_ffmpeg(arch_key: str) -> tuple[str, dict[str, bool]] | None:
    """Return vendor ffmpeg when install marker proves prior verification."""
    target = vendor_ffmpeg_dir(arch_key) / "bin" / "ffmpeg"
    path = str(target)
    if not target.is_file() or not _ffmpeg_install_sane(path):
        return None
    probes = _load_vendor_probes(arch_key)
    if probes and _tiktok_hevc_capable_from_probes(probes):
        return path, probes
    return None


def set_startup_ffmpeg_info(info: dict[str, Any]) -> None:
    global _startup_ffmpeg_info
    _startup_ffmpeg_info = info


def get_startup_ffmpeg_info() -> dict[str, Any] | None:
    return _startup_ffmpeg_info


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
    trusted = _trusted_vendor_ffmpeg(arch_key)
    if trusted:
        return trusted[0]

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

        ffmpeg_bin, ffprobe_bin = _extract_ffmpeg_tree(archive_path, install_dir)
        capable, probes = verify_installed_ffmpeg(str(ffmpeg_bin))
        if not capable:
            raise RuntimeError(
                f"Installed FFmpeg at {ffmpeg_bin} failed HEVC FLV verification "
                f"(legacy={probes['legacy']}, enhanced={probes['enhanced']}, "
                f"roundtrip={probes['roundtrip']}, ffprobe={ffprobe_bin.is_file()})"
            )
        _save_vendor_probes(arch_key, probes)
        logger.info(
            f"Installed capable FFmpeg: {ffmpeg_bin} "
            f"(HEVC probe legacy={probes['legacy']} enhanced={probes['enhanced']} "
            f"roundtrip={probes['roundtrip']})"
        )
        return str(ffmpeg_bin)


def normalize_cdn_url(url: str) -> str:
    """Identity for CDN URLs ignoring signed query parameters."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def linux_ffmpeg_requirement_help() -> str:
    """Operator guidance when Linux startup cannot obtain capable FFmpeg."""
    vendor_root = find_repo_root() / ".vendor" / "ffmpeg"
    return (
        f"Recorder stopped on Linux: TikTok-capable FFmpeg is mandatory. "
        f"Install BtbN FFmpeg {FFMPEG_PIN} under {vendor_root} "
        "(auto-download on startup when HTTPS to github.com works and the directory "
        "is writable), or pass --ffmpeg-path to FFmpeg 8+ that demuxes TikTok "
        "legacy HEVC FLV (codec id 12)."
    )


def resolve_ffmpeg_path(ffmpeg_path: str | None = None) -> str:
    """
    Return an ffmpeg binary that can demux TikTok legacy HEVC FLV when possible.

    Order: explicit path (if TikTok-capable) → existing Linux vendor → PATH ffmpeg
    → Linux vendor install. Roundtrip-only builds (e.g. Debian 7.x) are not accepted.
    """
    linux = platform.system().lower() == "linux"
    arch_key = _linux_arch_key() if linux else None

    explicit: str | None = None
    if ffmpeg_path:
        explicit = shutil.which(ffmpeg_path) or str(Path(ffmpeg_path))

    def existing_vendor() -> str | None:
        if not linux or arch_key is None:
            return None
        trusted = _trusted_vendor_ffmpeg(arch_key)
        return trusted[0] if trusted else None

    if explicit and ffmpeg_tiktok_hevc_capable(explicit):
        return explicit

    vendor = existing_vendor()
    if vendor:
        if explicit and Path(explicit).resolve() != Path(vendor).resolve():
            logger.info(
                f"Using vendor FFmpeg instead of {explicit} "
                f"({ffmpeg_version_line(explicit)} cannot demux TikTok legacy HEVC FLV)"
            )
        return vendor

    if not explicit:
        path_ffmpeg = shutil.which("ffmpeg")
        if path_ffmpeg and ffmpeg_tiktok_hevc_capable(path_ffmpeg):
            return path_ffmpeg

    if linux and arch_key:
        try:
            return install_linux_vendor_ffmpeg(arch_key)
        except Exception as exc:
            raise FfmpegRequirementError(
                f"Could not install or verify BtbN FFmpeg {FFMPEG_PIN} for TikTok "
                f"HEVC FLV: {exc}"
            ) from exc
    if linux:
        raise FfmpegRequirementError(
            f"Unsupported Linux architecture for vendor FFmpeg: {platform.machine()}. "
            "TikTok HEVC FLV recording requires FFmpeg 8+ with legacy codec-12 demux."
        )

    fallback = explicit or shutil.which("ffmpeg")
    if fallback:
        if not ffmpeg_tiktok_hevc_capable(fallback):
            logger.warning(
                f"FFmpeg at {fallback} cannot demux TikTok legacy HEVC FLV "
                f"({ffmpeg_version_line(fallback)}). "
                "Install FFmpeg 8.0+ or allow automatic vendor install on Linux."
            )
        return fallback

    raise FileNotFoundError("FFmpeg binary not found")


def log_ffmpeg_status(
    ffmpeg_path: str | None = None, *, info: dict[str, Any] | None = None
) -> None:
    details = info or describe_ffmpeg_binary(ffmpeg_path)
    probes = details.get("hevc_probe") or {}
    status = (
        "capable for TikTok HEVC FLV"
        if details["hevc_capable"]
        else "NOT capable for TikTok HEVC FLV"
    )
    logger.info(
        f"FFmpeg: {details['path']} ({details['version']}) — {status} "
        f"[probe legacy={probes.get('legacy')} enhanced={probes.get('enhanced')} "
        f"roundtrip={probes.get('roundtrip')}]"
    )


def describe_ffmpeg_binary(
    ffmpeg_path: str | None,
    *,
    probes: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Return resolved FFmpeg path, install source, version, and HEVC capability."""
    if not ffmpeg_path:
        return {
            "path": None,
            "source": "missing",
            "version": None,
            "hevc_capable": False,
            "hevc_probe": _empty_hevc_probe(),
        }

    cached = get_startup_ffmpeg_info()
    if cached and cached.get("path") and not probes:
        try:
            if Path(cached["path"]).resolve() == Path(ffmpeg_path).resolve():
                return dict(cached)
        except OSError:
            if cached.get("path") == ffmpeg_path:
                return dict(cached)

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
    if probes is None and source == "vendor":
        arch_key = _vendor_arch_for_path(resolved)
        if arch_key:
            trusted = _trusted_vendor_ffmpeg(arch_key)
            if trusted and trusted[0] == resolved:
                probes = trusted[1]

    if probes is None:
        _, probes = (
            verify_installed_ffmpeg(ffmpeg_path)
            if exists
            else (False, _empty_hevc_probe())
        )
    capable = _tiktok_hevc_capable_from_probes(probes)

    return {
        "path": resolved,
        "source": source,
        "version": ffmpeg_version_line(ffmpeg_path) if exists else None,
        "hevc_capable": capable,
        "hevc_probe": probes,
    }
