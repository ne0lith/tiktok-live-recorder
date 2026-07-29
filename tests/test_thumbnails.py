from pathlib import Path
import os
from unittest.mock import patch

from tiktok_live_recorder.web.thumbnails import (
    THUMB_SUFFIX,
    _temp_thumbnail_path,
    ensure_thumbnail,
    thumbnail_is_fresh,
    thumbnail_path_for,
    thumbnail_url,
)


def test_thumbnail_path_for():
    video = Path("/output/user/TK_alpha_2026.mp4")
    assert thumbnail_path_for(video) == Path("/output/user/TK_alpha_2026.thumb.jpg")
    assert thumbnail_path_for(video).name.endswith(THUMB_SUFFIX)


def test_thumbnail_url_paths():
    assert (
        thumbnail_url("alpha", "TK_alpha_2026.mp4")
        == "/media/alpha/TK_alpha_2026.mp4/thumb"
    )
    assert (
        thumbnail_url("alpha", "old.mp4", subdir="legacy")
        == "/media/alpha/legacy/old.mp4/thumb"
    )


def test_temp_thumbnail_path_keeps_jpg_extension():
    thumb = Path("/output/user/TK_alpha.thumb.jpg")
    assert _temp_thumbnail_path(thumb) == Path("/output/user/TK_alpha.thumb.tmp.jpg")


def test_thumbnail_is_fresh(tmp_path):
    video = tmp_path / "TK_alpha.mp4"
    thumb = thumbnail_path_for(video)
    video.write_bytes(b"video")
    assert thumbnail_is_fresh(video, thumb) is False

    thumb.write_bytes(b"jpeg")
    os.utime(thumb, (1_000_000, 1_000_000))
    os.utime(video, (900_000, 900_000))
    assert thumbnail_is_fresh(video, thumb) is True

    video.write_bytes(b"updated-video")
    os.utime(video, (1_100_000, 1_100_000))
    assert thumbnail_is_fresh(video, thumb) is False


def test_ensure_thumbnail_generates_once(tmp_path):
    video = tmp_path / "TK_alpha.mp4"
    video.write_bytes(b"video")
    thumb = thumbnail_path_for(video)

    def fake_generate(video_path, thumb_path, *, ffmpeg_path):
        thumb_path.write_bytes(b"jpeg")
        return True

    with patch(
        "tiktok_live_recorder.web.thumbnails.generate_thumbnail",
        side_effect=fake_generate,
    ) as generate:
        first = ensure_thumbnail(video, ffmpeg_path="/usr/bin/ffmpeg")
        second = ensure_thumbnail(video, ffmpeg_path="/usr/bin/ffmpeg")

    assert first == thumb
    assert second == thumb
    generate.assert_called_once()


def test_ensure_thumbnail_returns_none_when_generation_fails(tmp_path):
    video = tmp_path / "TK_alpha.mp4"
    video.write_bytes(b"video")

    with patch(
        "tiktok_live_recorder.web.thumbnails.generate_thumbnail",
        return_value=False,
    ):
        assert ensure_thumbnail(video, ffmpeg_path="/usr/bin/ffmpeg") is None
