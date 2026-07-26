import os
import tempfile
import time
from pathlib import Path

import ffmpeg

from tiktok_live_recorder.utils.flv_hevc_rewrite import (
    file_needs_legacy_hevc_rewrite,
    rewrite_legacy_hevc_flv,
)
from tiktok_live_recorder.utils.logger_manager import logger


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
        path = Path(ffmpeg_path)
        if path.name == "ffmpeg":
            candidate = path.with_name("ffprobe")
            if candidate.is_file():
                return str(candidate)
        return str(ffmpeg_path).replace("ffmpeg", "ffprobe")

    @staticmethod
    def _is_hevc_demux_error(stderr: str) -> bool:
        text = stderr or ""
        return (
            "Video codec (c) is not implemented" in text
            or "0x000C" in text
            or "unknown codec" in text.lower()
        )

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

        output_args = {
            "vf": vf,
            "c:v": "libx264",
            "preset": "veryfast",
            "c:a": "aac",
            "b:a": "160k",
            "movflags": "+faststart",
            "avoid_negative_ts": "make_zero",
            "pix_fmt": "yuv420p",
        }

        if bitrate:
            output_args["b:v"] = bitrate
        else:
            output_args["crf"] = "20"

        try:
            (
                ffmpeg.input(input_file, fflags="+genpts+igndts")
                .output(output_file, **output_args)
                .overwrite_output()
                .run(quiet=True, cmd=ffmpeg_cmd)
            )
            return True
        except ffmpeg.Error as e:
            stderr = e.stderr.decode() if hasattr(e, "stderr") and e.stderr else str(e)
            logger.error(f"ffmpeg conversion failed: {stderr}")
            if VideoManagement._is_hevc_demux_error(stderr):
                logger.warning(
                    "TikTok legacy HEVC-in-FLV detected (codec id 12). "
                    "Will try Enhanced FLV rewrite if available."
                )
            return False

    @staticmethod
    def convert_flv_to_mp4(file, bitrate=None, ffmpeg_path=None) -> bool:
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

        try:
            if rewrite_source != file and VideoManagement._run_ffmpeg_convert(
                rewrite_source,
                output_file,
                bitrate=bitrate,
                ffmpeg_cmd=ffmpeg_cmd,
                ffprobe_cmd=ffprobe_cmd,
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
