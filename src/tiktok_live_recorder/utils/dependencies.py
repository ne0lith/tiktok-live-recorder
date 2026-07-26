import platform
import shutil
import subprocess
from pathlib import Path
from subprocess import SubprocessError

from .ffmpeg_setup import log_ffmpeg_status, resolve_ffmpeg_path
from .logger_manager import logger


def check_ffmpeg_binary(ffmpeg_path="ffmpeg"):
    try:
        subprocess.run(
            [ffmpeg_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        return True
    except FileNotFoundError:
        logger.error("FFmpeg binary is not installed")
        return False


def install_ffmpeg_binary():
    try:
        logger.error("FFmpeg is required for recording conversion.")
        if platform.system().lower() == "linux":
            logger.info(
                "On Linux, install FFmpeg manually or re-run the recorder so it can "
                "fetch BtbN FFmpeg n8.1 into .vendor/ffmpeg/ automatically."
            )
            logger.info(
                "Distro packages (apt/dnf/pacman) are optional; the vendor build is "
                "used when missing or too old for TikTok HEVC FLV."
            )

        elif platform.system().lower() == "windows":
            logger.info(
                "choco install ffmpeg or follow: https://phoenixnap.com/kb/ffmpeg-windows"
            )

        elif platform.system().lower() == "darwin":
            logger.info("brew install ffmpeg")

        else:
            logger.info(f"OS not supported: {platform}")

    except Exception as e:
        logger.error(f"Error: {e}")

    exit(1)


def check_distro_library():
    try:
        import distro

        _ = distro  # to avoid linting issues

        return True
    except ModuleNotFoundError:
        logger.error("distro library is not installed")
        return False


def check_ffmpeg_library():
    try:
        import ffmpeg

        _ = ffmpeg  # to avoid linting issues

        return True
    except ModuleNotFoundError:
        logger.error("ffmpeg-python library is not installed")
        return False


def check_argparse_library():
    try:
        import argparse

        _ = argparse  # to avoid linting issues

        return True
    except ModuleNotFoundError:
        logger.error("argparse library is not installed")
        return False


def check_curl_cffi_library():
    try:
        from .utils import is_termux

        if is_termux():
            return True

        import curl_cffi

        _ = curl_cffi  # to avoid linting issues

        return True
    except ModuleNotFoundError:
        logger.error("curl_cffi library is not installed")
        return False


def check_requests_library():
    try:
        import requests

        _ = requests  # to avoid linting issues

        return True
    except ModuleNotFoundError:
        logger.error("requests library is not installed")
        return False


def check_telethon_library():
    try:
        import telethon

        _ = telethon  # to avoid linting issues

        return True
    except ModuleNotFoundError:
        logger.error("telethon library is not installed")
        return False


def install_requirements():
    try:
        print()
        logger.error("Installing requirements...\n")

        subprocess.run(
            ["uv", "sync", "--no-dev"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            check=True,
        )
        logger.info("Requirements installed successfully\n")
    except SubprocessError as e:
        logger.error(f"Error: {e}")
        exit(1)


def check_and_install_dependencies():
    logger.info("Checking and Installing dependencies...")

    dependencies = [
        check_distro_library(),
        check_ffmpeg_library(),
        check_argparse_library(),
        check_curl_cffi_library(),
        check_requests_library(),
        check_telethon_library(),
    ]

    if False in dependencies:
        install_requirements()


def _ffmpeg_binary_missing(ffmpeg_path: str | None) -> bool:
    requested = ffmpeg_path or "ffmpeg"
    if shutil.which(requested):
        return False
    explicit = Path(requested)
    if explicit.is_file():
        return False
    try:
        subprocess.run(
            [requested],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            check=False,
        )
        return False
    except FileNotFoundError:
        return True


def check_ffmpeg(ffmpeg_path: str | None = None) -> str | None:
    """
    Ensure ffmpeg exists and return the resolved binary path (vendor install on Linux).
    """
    if _ffmpeg_binary_missing(ffmpeg_path):
        if platform.system().lower() != "linux":
            logger.error("FFmpeg binary is not installed")
            install_ffmpeg_binary()
            return None
        logger.info(
            "FFmpeg not found on PATH; installing capable vendor build for Linux..."
        )

    try:
        resolved = resolve_ffmpeg_path(ffmpeg_path)
    except FileNotFoundError:
        install_ffmpeg_binary()
        return None

    log_ffmpeg_status(resolved)
    return resolved
