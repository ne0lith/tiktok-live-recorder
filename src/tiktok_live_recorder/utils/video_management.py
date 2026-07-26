import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import ffmpeg

from tiktok_live_recorder.utils.ffmpeg_setup import ffprobe_for
from tiktok_live_recorder.utils.flv_hevc_rewrite import (
    file_needs_legacy_hevc_rewrite,
    rewrite_legacy_hevc_flv,
)
from tiktok_live_recorder.utils.logger_manager import logger

ConvertProgressCallback = Callable[[dict[str, Any]], None]


class VideoManagement:
    @staticmethod
    def wait_for_file_release(file, timeout=10):
        """
        Wait until the file is released (not locked anymore) or timeout is reached.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with open(file, "ab"):
                    return True
            except PermissionError:
                time.sleep(0.5)
        return False

    @staticmethod
    def _even(value: int) -> int:
        return max(2, value - (value % 2))

    @staticmethod
    def _ffprobe_cmd(ffmpeg_path: str | None) -> str:
        if not ffmpeg_path:
            return "ffprobe"
        return ffprobe_for(ffmpeg_path)

    @staticmethod
    def _is_hevc_demux_error(stderr: str) -> bool:
        text = stderr or ""
        return (
            "Video codec (c) is not implemented" in text
            or "0x000C" in text
            or "unknown codec" in text.lower()
        )

    @staticmethod
    def parse_ffmpeg_progress_line(line: str) -> dict[str, Any] | None:
        stripped = line.strip()
        if not stripped or "=" not in stripped:
            return None
        key, value = stripped.split("=", 1)
        if key == "out_time_us":
            return {"out_time_us": int(value)}
        if key == "out_time_ms":
            return {"out_time_us": int(value) * 1000}
        if key == "out_time":
            return {"out_time": value}
        if key == "progress":
            return {"progress": value}
        return None

    @staticmethod
    def progress_percent(
        out_time_us: int, duration_seconds: float | None
    ) -> int | None:
        if not duration_seconds or duration_seconds <= 0:
            return None
        total_us = int(duration_seconds * 1_000_000)
        if total_us <= 0:
            return None
        return max(0, min(99, int(out_time_us / total_us * 100)))

    @staticmethod
    def _probe_duration_seconds(input_file: str, ffprobe_cmd: str) -> float | None:
        try:
            probe = ffmpeg.probe(input_file, cmd=ffprobe_cmd)
            duration = probe.get("format", {}).get("duration")
            if duration:
                return float(duration)
            for stream in probe.get("streams", []):
                if stream.get("codec_type") == "video" and stream.get("duration"):
                    return float(stream["duration"])
        except Exception as exc:
            logger.warning(f"Could not probe duration for {input_file}: {exc}")
        return None

    @staticmethod
    def _emit_convert_progress(
        on_progress: ConvertProgressCallback | None,
        *,
        percent: int | None,
        duration_seconds: float | None,
        out_time_us: int | None = None,
        phase: str = "encode",
    ) -> None:
        if on_progress is None:
            return
        payload: dict[str, Any] = {"phase": phase}
        if percent is not None:
            payload["percent"] = percent
        if duration_seconds is not None:
            payload["duration_seconds"] = round(duration_seconds, 3)
        if out_time_us is not None and duration_seconds:
            payload["out_time_seconds"] = round(out_time_us / 1_000_000, 3)
        on_progress(payload)

    @staticmethod
    def _canvas_from_source(file: str, ffprobe_cmd: str) -> tuple[int, int]:
        """
        Use the file's initial coded size as the fixed output canvas.

        TikTok often nudges resolution mid-live (nearby widths/heights, not just
        portrait/landscape flips). Re-encoding everything into that first size
        keeps one SPS/PPS for the whole MP4 so seeking stays valid.
        """
        probe = ffmpeg.probe(file, cmd=ffprobe_cmd)
        video = next(
            (
                stream
                for stream in probe["streams"]
                if stream.get("codec_type") == "video"
            ),
            None,
        )
        if not video:
            return 1080, 1920

        width = VideoManagement._even(int(video.get("width") or 1080))
        height = VideoManagement._even(int(video.get("height") or 1920))
        return width, height

    @staticmethod
    def _run_ffmpeg_convert(
        input_file: str,
        output_file: str,
        *,
        bitrate: str | None,
        ffmpeg_cmd: str,
        ffprobe_cmd: str,
        on_progress: ConvertProgressCallback | None = None,
        phase: str = "encode",
    ) -> bool:
        try:
            width, height = VideoManagement._canvas_from_source(input_file, ffprobe_cmd)
        except Exception as exc:
            logger.warning(
                f"Could not probe {input_file} for canvas size ({exc}); using 1080x1920."
            )
            width, height = 1080, 1920

        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1"
        )
        logger.info(f"Re-encoding to fixed canvas {width}x{height} for seek-safe MP4")

        duration_seconds = VideoManagement._probe_duration_seconds(
            input_file, ffprobe_cmd
        )
        VideoManagement._emit_convert_progress(
            on_progress,
            percent=0,
            duration_seconds=duration_seconds,
            phase=phase,
        )

        cmd = [
            ffmpeg_cmd,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostats",
            "-progress",
            "pipe:1",
            "-y",
            "-fflags",
            "+genpts+igndts",
            "-i",
            input_file,
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            "-pix_fmt",
            "yuv420p",
        ]
        if bitrate:
            cmd.extend(["-b:v", bitrate])
        else:
            cmd.extend(["-crf", "20"])
        cmd.append(output_file)

        last_percent = -1
        last_emit_at = 0.0
        out_time_us = 0

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                parsed = VideoManagement.parse_ffmpeg_progress_line(line)
                if not parsed:
                    continue
                if "out_time_us" in parsed:
                    out_time_us = parsed["out_time_us"]
                if parsed.get("progress") == "end":
                    out_time_us = int((duration_seconds or 0) * 1_000_000)
                percent = VideoManagement.progress_percent(
                    out_time_us, duration_seconds
                )
                if percent is None:
                    continue
                now = time.time()
                if percent != last_percent or now - last_emit_at >= 0.5:
                    last_percent = percent
                    last_emit_at = now
                    VideoManagement._emit_convert_progress(
                        on_progress,
                        percent=percent,
                        duration_seconds=duration_seconds,
                        out_time_us=out_time_us,
                        phase=phase,
                    )

            stderr = process.stderr.read() if process.stderr else ""
            returncode = process.wait()
            if returncode == 0:
                VideoManagement._emit_convert_progress(
                    on_progress,
                    percent=100,
                    duration_seconds=duration_seconds,
                    out_time_us=out_time_us,
                    phase=phase,
                )
                return True

            logger.error(f"ffmpeg conversion failed: {stderr}")
            if VideoManagement._is_hevc_demux_error(stderr):
                logger.warning(
                    "TikTok legacy HEVC-in-FLV detected (codec id 12). "
                    "Will try Enhanced FLV rewrite if available."
                )
            return False
        except OSError as exc:
            logger.error(f"ffmpeg conversion failed: {exc}")
            return False

    @staticmethod
    def convert_flv_to_mp4(
        file,
        bitrate=None,
        ffmpeg_path=None,
        on_progress: ConvertProgressCallback | None = None,
    ) -> bool:
        """
        Convert a live FLV recording into a seekable MP4.

        Returns True when the final MP4 was written. On failure the source
        *_flv.mp4 is kept for salvage.
        """
        logger.info("Converting {} to MP4 format...".format(file))

        if not VideoManagement.wait_for_file_release(file):
            logger.error(
                f"File {file} is still locked after waiting. Skipping conversion."
            )
            return False

        output_file = file.replace("_flv.mp4", ".mp4")
        ffmpeg_cmd = ffmpeg_path or "ffmpeg"
        ffprobe_cmd = VideoManagement._ffprobe_cmd(ffmpeg_path)

        if VideoManagement._run_ffmpeg_convert(
            file,
            output_file,
            bitrate=bitrate,
            ffmpeg_cmd=ffmpeg_cmd,
            ffprobe_cmd=ffprobe_cmd,
            on_progress=on_progress,
        ):
            os.remove(file)
            logger.info(f"Finished converting {Path(output_file).resolve()}\n")
            return True

        rewrite_source = file
        rewritten_path: str | None = None
        if file_needs_legacy_hevc_rewrite(file):
            with tempfile.NamedTemporaryFile(
                suffix="_rewritten.flv", delete=False
            ) as tmp:
                rewritten_path = tmp.name
            rewrite_legacy_hevc_flv(Path(file), Path(rewritten_path))
            rewrite_source = rewritten_path
            logger.info("Retrying conversion after legacy HEVC → Enhanced hvc1 rewrite")
            VideoManagement._emit_convert_progress(
                on_progress,
                percent=0,
                duration_seconds=VideoManagement._probe_duration_seconds(
                    rewrite_source, ffprobe_cmd
                ),
                phase="rewrite",
            )

        try:
            if rewrite_source != file and VideoManagement._run_ffmpeg_convert(
                rewrite_source,
                output_file,
                bitrate=bitrate,
                ffmpeg_cmd=ffmpeg_cmd,
                ffprobe_cmd=ffprobe_cmd,
                on_progress=on_progress,
                phase="rewrite",
            ):
                os.remove(file)
                logger.info(f"Finished converting {Path(output_file).resolve()}\n")
                return True
        finally:
            if rewritten_path:
                Path(rewritten_path).unlink(missing_ok=True)

        logger.error(
            f"Conversion failed; left raw recording at {Path(file).resolve()}. "
            "Use the dashboard 'Convert leftover FLV' action to retry."
        )
        return False
