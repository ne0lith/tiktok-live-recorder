"""Convert one leftover ``*_flv.mp4`` using the in-app salvage pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tiktok_live_recorder.utils.dependencies import check_ffmpeg
from tiktok_live_recorder.utils.video_management import VideoManagement

_FLV_SUFFIX = "_flv.mp4"


def is_leftover_flv_name(name: str) -> bool:
    return name.endswith(_FLV_SUFFIX)


def convert_leftover_flv(path: str, ffmpeg_path: str | None = None) -> bool:
    """Run ``VideoManagement.convert_flv_to_mp4`` on a leftover recording.

    The source ``*_flv.mp4`` is deleted on success (same as the recorder).
    """
    if not is_leftover_flv_name(Path(path).name):
        return False
    resolved = ffmpeg_path or check_ffmpeg(None)
    return VideoManagement.convert_flv_to_mp4(path, ffmpeg_path=resolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert one leftover *_flv.mp4 with the recorder salvage pipeline "
            "(libx264, HEVC rewrite, MKV remux). Deletes the source on success."
        )
    )
    parser.add_argument(
        "file",
        help="Path to a leftover TK_*_flv.mp4 recording",
    )
    parser.add_argument(
        "--ffmpeg-path",
        default=None,
        help="FFmpeg binary (default: recorder vendor/PATH resolution)",
    )
    args = parser.parse_args(argv)
    path = Path(args.file)
    if not is_leftover_flv_name(path.name):
        print(f"not a leftover FLV (need *_flv.mp4): {path.name}", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 2
    ok = convert_leftover_flv(str(path), ffmpeg_path=args.ffmpeg_path)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
