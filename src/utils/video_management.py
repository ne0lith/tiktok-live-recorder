import os
import time
from pathlib import Path

import ffmpeg

from utils.logger_manager import logger


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
    def convert_flv_to_mp4(file, bitrate=None, ffmpeg_path=None):
        """
        Convert a live FLV recording into a seekable MP4.

        Live TikTok streams often change resolution mid-session (sometimes only
        slightly). Stream-copy remux keeps the first SPS/PPS, so seeking past a
        change breaks the timeline and shows color garbage.

        Always re-encode onto a fixed canvas derived from the source's initial
        resolution so every frame shares one set of codec parameters.
        """
        logger.info("Converting {} to MP4 format...".format(file))

        if not VideoManagement.wait_for_file_release(file):
            logger.error(
                f"File {file} is still locked after waiting. Skipping conversion."
            )
            return

        output_file = file.replace("_flv.mp4", ".mp4")
        ffmpeg_cmd = ffmpeg_path or "ffmpeg"
        ffprobe_cmd = (
            str(ffmpeg_path).replace("ffmpeg", "ffprobe") if ffmpeg_path else "ffprobe"
        )

        try:
            width, height = VideoManagement._canvas_from_source(file, ffprobe_cmd)
        except Exception as exc:
            logger.warning(
                f"Could not probe {file} for canvas size ({exc}); using 1080x1920."
            )
            width, height = 1080, 1920

        # Nearby mid-stream sizes are scaled/padded into the initial canvas.
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
                ffmpeg.input(file, fflags="+genpts+igndts")
                .output(output_file, **output_args)
                .overwrite_output()
                .run(quiet=True, cmd=ffmpeg_cmd)
            )
        except ffmpeg.Error as e:
            logger.error(
                "ffmpeg conversion failed: "
                f"{e.stderr.decode() if hasattr(e, 'stderr') and e.stderr else e}"
            )
            return

        os.remove(file)
        logger.info(f"Finished converting {Path(output_file).resolve()}\n")
