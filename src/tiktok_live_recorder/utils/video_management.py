import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import ffmpeg

from tiktok_live_recorder.utils.ffmpeg_setup import ffprobe_for
from tiktok_live_recorder.utils.flv_hevc_rewrite import (
    file_needs_legacy_hevc_rewrite,
    rewrite_legacy_hevc_flv,
)
from tiktok_live_recorder.utils.logger_manager import logger

ConvertProgressCallback = Callable[[dict[str, Any]], None]

AudioMode = Literal["encode", "copy", "none"]


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
    def _parse_progress_int(value: str) -> int | None:
        stripped = value.strip()
        if not stripped or not re.fullmatch(r"\d+", stripped):
            return None
        return int(stripped)

    @staticmethod
    def parse_ffmpeg_progress_line(line: str) -> dict[str, Any] | None:
        stripped = line.strip()
        if not stripped or "=" not in stripped:
            return None
        key, value = stripped.split("=", 1)
        if key == "out_time_us":
            parsed = VideoManagement._parse_progress_int(value)
            return {"out_time_us": parsed} if parsed is not None else None
        if key == "out_time_ms":
            parsed = VideoManagement._parse_progress_int(value)
            return {"out_time_us": parsed * 1000} if parsed is not None else None
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
    def _probe_video_info(input_file: str, ffprobe_cmd: str) -> tuple[str, str]:
        try:
            result = subprocess.run(
                [
                    ffprobe_cmd,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name,pix_fmt",
                    "-of",
                    "csv=p=0",
                    input_file,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            parts = [part.strip() for part in (result.stdout or "").split(",")]
            if len(parts) >= 2:
                return parts[0].lower(), parts[1].lower()
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            pass
        return "", ""

    @staticmethod
    def _probe_has_audio(input_file: str, ffprobe_cmd: str) -> bool:
        try:
            result = subprocess.run(
                [
                    ffprobe_cmd,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "csv=p=0",
                    input_file,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return "audio" in (result.stdout or "").lower()
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            return False

    @staticmethod
    def output_is_dashboard_playable(output_file: str, ffprobe_cmd: str) -> bool:
        path = Path(output_file)
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        codec, pix_fmt = VideoManagement._probe_video_info(output_file, ffprobe_cmd)
        return codec == "h264" and pix_fmt == "yuv420p"

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
    def _build_vf(
        width: int, height: int, *, salvage: bool = False, pix_fmt: str = ""
    ) -> str:
        range_fix = ""
        if pix_fmt == "yuvj420p":
            range_fix = ",scale=in_range=full:out_range=limited"
        filters = [
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            f"format=yuv420p{range_fix}",
            "setsar=1",
        ]
        if salvage:
            filters.append("setpts=PTS-STARTPTS")
        return ",".join(filters)

    @staticmethod
    def _audio_args(audio_mode: AudioMode) -> list[str]:
        if audio_mode == "none":
            return ["-an"]
        if audio_mode == "copy":
            return ["-c:a", "copy"]
        return [
            "-af",
            "aresample=async=1:first_pts=0",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ac",
            "2",
        ]

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
        salvage: bool = False,
        audio_mode: AudioMode = "encode",
        remux_copy: bool = False,
    ) -> bool:
        try:
            width, height = VideoManagement._canvas_from_source(input_file, ffprobe_cmd)
        except Exception as exc:
            logger.warning(
                f"Could not probe {input_file} for canvas size ({exc}); using 1080x1920."
            )
            width, height = 1080, 1920

        _, src_pix_fmt = VideoManagement._probe_video_info(input_file, ffprobe_cmd)
        vf = VideoManagement._build_vf(
            width, height, salvage=salvage, pix_fmt=src_pix_fmt
        )
        if salvage:
            logger.info(f"Salvage re-encode to fixed canvas {width}x{height} ({phase})")
        else:
            logger.info(
                f"Re-encoding to fixed canvas {width}x{height} for seek-safe MP4"
            )

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
        ]
        if remux_copy:
            cmd.extend(
                [
                    "-i",
                    input_file,
                    "-map",
                    "0:v:0?",
                    "-map",
                    "0:a:0?",
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    "-tag:v",
                    "avc1",
                ]
            )
        else:
            input_flags = ["+genpts+igndts"]
            if salvage:
                input_flags.append("discardcorrupt")
            cmd.extend(["-fflags", "+".join(input_flags)])
            if salvage:
                cmd.extend(["-err_detect", "ignore_err"])
            cmd.extend(
                [
                    "-i",
                    input_file,
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-pix_fmt",
                    "yuv420p",
                ]
            )
            cmd.extend(VideoManagement._audio_args(audio_mode))
            if salvage:
                cmd.extend(
                    [
                        "-reset_timestamps",
                        "1",
                        "-max_muxing_queue_size",
                        "9999",
                        "-tag:v",
                        "avc1",
                    ]
                )
            if not output_file.lower().endswith(".mkv"):
                cmd.extend(
                    [
                        "-movflags",
                        "+faststart",
                    ]
                )
            cmd.extend(
                [
                    "-avoid_negative_ts",
                    "make_zero",
                ]
            )
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
                try:
                    parsed = VideoManagement.parse_ffmpeg_progress_line(line)
                except (TypeError, ValueError) as exc:
                    logger.debug("Ignoring ffmpeg progress line: %s (%s)", line, exc)
                    continue
                if not parsed:
                    continue
                if parsed.get("out_time_us") is not None:
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

            logger.error(f"ffmpeg conversion failed ({phase}): {stderr}")
            if VideoManagement._is_hevc_demux_error(stderr):
                logger.warning(
                    "TikTok legacy HEVC-in-FLV detected (codec id 12). "
                    "Will try Enhanced FLV rewrite if available."
                )
            return False
        except OSError as exc:
            logger.error(f"ffmpeg conversion failed ({phase}): {exc}")
            return False

    @staticmethod
    def _try_convert_pass(
        input_file: str,
        output_file: str,
        *,
        bitrate: str | None,
        ffmpeg_cmd: str,
        ffprobe_cmd: str,
        on_progress: ConvertProgressCallback | None,
        phase: str,
        salvage: bool = False,
        audio_mode: AudioMode = "encode",
    ) -> bool:
        Path(output_file).unlink(missing_ok=True)
        if not VideoManagement._run_ffmpeg_convert(
            input_file,
            output_file,
            bitrate=bitrate,
            ffmpeg_cmd=ffmpeg_cmd,
            ffprobe_cmd=ffprobe_cmd,
            on_progress=on_progress,
            phase=phase,
            salvage=salvage,
            audio_mode=audio_mode,
        ):
            return False
        if VideoManagement.output_is_dashboard_playable(output_file, ffprobe_cmd):
            return True
        logger.warning(
            "Conversion produced non-playable output (%s); trying next pass",
            output_file,
        )
        Path(output_file).unlink(missing_ok=True)
        return False

    @staticmethod
    def _try_mkv_salvage_pass(
        input_file: str,
        output_file: str,
        *,
        bitrate: str | None,
        ffmpeg_cmd: str,
        ffprobe_cmd: str,
        on_progress: ConvertProgressCallback | None,
        audio_mode: AudioMode,
    ) -> bool:
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as tmp:
            mkv_path = tmp.name
        try:
            phase = f"mkv-{audio_mode}"
            if not VideoManagement._try_convert_pass(
                input_file,
                mkv_path,
                bitrate=bitrate,
                ffmpeg_cmd=ffmpeg_cmd,
                ffprobe_cmd=ffprobe_cmd,
                on_progress=on_progress,
                phase=phase,
                salvage=True,
                audio_mode=audio_mode,
            ):
                return False
            Path(output_file).unlink(missing_ok=True)
            if not VideoManagement._run_ffmpeg_convert(
                mkv_path,
                output_file,
                bitrate=bitrate,
                ffmpeg_cmd=ffmpeg_cmd,
                ffprobe_cmd=ffprobe_cmd,
                on_progress=on_progress,
                phase=f"{phase}+mp4",
                remux_copy=True,
            ):
                return False
            if VideoManagement.output_is_dashboard_playable(output_file, ffprobe_cmd):
                return True
            Path(output_file).unlink(missing_ok=True)
            return False
        finally:
            Path(mkv_path).unlink(missing_ok=True)

    @staticmethod
    def _salvage_audio_modes(input_file: str, ffprobe_cmd: str) -> list[AudioMode]:
        if not VideoManagement._probe_has_audio(input_file, ffprobe_cmd):
            return ["none"]
        return ["copy", "encode", "none"]

    @staticmethod
    def convert_flv_to_mp4(
        file,
        bitrate=None,
        ffmpeg_path=None,
        on_progress: ConvertProgressCallback | None = None,
    ) -> bool:
        """
        Convert a live FLV recording into a seekable MP4.

        Returns True when the final MP4 was written and ffprobe-verified playable.
        On failure the source *_flv.mp4 is kept for salvage.
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

        if VideoManagement._try_convert_pass(
            file,
            output_file,
            bitrate=bitrate,
            ffmpeg_cmd=ffmpeg_cmd,
            ffprobe_cmd=ffprobe_cmd,
            on_progress=on_progress,
            phase="encode",
        ):
            os.remove(file)
            logger.info(f"Finished converting {Path(output_file).resolve()}\n")
            return True

        for audio_mode in VideoManagement._salvage_audio_modes(file, ffprobe_cmd):
            if VideoManagement._try_convert_pass(
                file,
                output_file,
                bitrate=bitrate,
                ffmpeg_cmd=ffmpeg_cmd,
                ffprobe_cmd=ffprobe_cmd,
                on_progress=on_progress,
                phase=f"salvage-{audio_mode}",
                salvage=True,
                audio_mode=audio_mode,
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
            if rewrite_source != file and VideoManagement._try_convert_pass(
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

        for audio_mode in VideoManagement._salvage_audio_modes(file, ffprobe_cmd):
            if VideoManagement._try_mkv_salvage_pass(
                file,
                output_file,
                bitrate=bitrate,
                ffmpeg_cmd=ffmpeg_cmd,
                ffprobe_cmd=ffprobe_cmd,
                on_progress=on_progress,
                audio_mode=audio_mode,
            ):
                os.remove(file)
                logger.info(f"Finished converting {Path(output_file).resolve()}\n")
                return True

        Path(output_file).unlink(missing_ok=True)
        logger.error(
            f"Conversion failed; left raw recording at {Path(file).resolve()}. "
            "Use the dashboard 'Move leftover FLVs' action to retry."
        )
        return False
