from pathlib import Path
import os
from unittest.mock import patch

from tiktok_live_recorder.web.thumbnails import (
    THUMB_SUFFIX,
    _temp_thumbnail_path,
    clear_thumbnail_probe_cache,
    ensure_thumbnail,
    is_flv_recording,
    purge_orphan_thumbnails,
    source_video_for_thumb_file,
    thumbnail_is_fresh,
    thumbnail_path_for,
    thumbnail_url,
    video_has_decodable_video,
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


def test_is_flv_recording():
    assert is_flv_recording(Path("TK_alpha_2026_flv.mp4")) is True
    assert is_flv_recording(Path("TK_alpha_2026.mp4")) is False


def test_ensure_thumbnail_skips_flv_recordings(tmp_path):
    video = tmp_path / "TK_alpha_2026_flv.mp4"
    video.write_bytes(b"flv-data")

    with patch(
        "tiktok_live_recorder.web.thumbnails.generate_thumbnail",
    ) as generate:
        assert ensure_thumbnail(video, ffmpeg_path="/usr/bin/ffmpeg") is None

    generate.assert_not_called()


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
    clear_thumbnail_probe_cache()

    def fake_generate(video_path, thumb_path, *, ffmpeg_path):
        thumb_path.write_bytes(b"jpeg")
        return True

    with (
        patch(
            "tiktok_live_recorder.web.thumbnails.video_has_decodable_video",
            return_value=True,
        ),
        patch(
            "tiktok_live_recorder.web.thumbnails.generate_thumbnail",
            side_effect=fake_generate,
        ) as generate,
    ):
        first = ensure_thumbnail(video, ffmpeg_path="/usr/bin/ffmpeg")
        second = ensure_thumbnail(video, ffmpeg_path="/usr/bin/ffmpeg")

    assert first == thumb
    assert second == thumb
    generate.assert_called_once()


def test_ensure_thumbnail_returns_none_when_generation_fails(tmp_path):
    video = tmp_path / "TK_alpha.mp4"
    video.write_bytes(b"video")
    clear_thumbnail_probe_cache()

    with (
        patch(
            "tiktok_live_recorder.web.thumbnails.video_has_decodable_video",
            return_value=True,
        ),
        patch(
            "tiktok_live_recorder.web.thumbnails.generate_thumbnail",
            return_value=False,
        ),
    ):
        assert ensure_thumbnail(video, ffmpeg_path="/usr/bin/ffmpeg") is None


def test_ensure_thumbnail_caches_unplayable_probe_failure(tmp_path):
    video = tmp_path / "TK_alpha.mp4"
    video.write_bytes(b"broken")
    clear_thumbnail_probe_cache()

    with (
        patch(
            "tiktok_live_recorder.web.thumbnails.video_has_decodable_video",
            return_value=False,
        ) as probe,
        patch(
            "tiktok_live_recorder.web.thumbnails.generate_thumbnail",
        ) as generate,
    ):
        assert ensure_thumbnail(video, ffmpeg_path="/usr/bin/ffmpeg") is None
        assert ensure_thumbnail(video, ffmpeg_path="/usr/bin/ffmpeg") is None

    probe.assert_called_once()
    generate.assert_not_called()


def test_video_has_decodable_video(tmp_path):
    video = tmp_path / "TK_alpha.mp4"
    video.write_bytes(b"not-a-real-video")

    with patch(
        "tiktok_live_recorder.web.thumbnails.subprocess.run",
        side_effect=__import__("subprocess").CalledProcessError(
            1, "ffprobe", stderr="moov atom not found"
        ),
    ):
        assert video_has_decodable_video(video, ffmpeg_path="/usr/bin/ffmpeg") is False


def test_source_video_for_thumb_file():
    thumb = Path("/output/user/TK_alpha_2026.thumb.jpg")
    assert source_video_for_thumb_file(thumb) == Path("/output/user/TK_alpha_2026.mp4")
    temp = Path("/output/user/TK_alpha_2026.thumb.tmp.jpg")
    assert source_video_for_thumb_file(temp) == Path("/output/user/TK_alpha_2026.mp4")
    legacy_temp = Path("/output/user/TK_alpha_2026.thumb.jpg.tmp")
    assert source_video_for_thumb_file(legacy_temp) == Path(
        "/output/user/TK_alpha_2026.mp4"
    )
    assert source_video_for_thumb_file(Path("/output/user/notes.jpg")) is None


def test_purge_orphan_thumbnails_keeps_paired_and_deletes_orphans(tmp_path):
    keep_video = tmp_path / "TK_alpha_2026.01.01_12-00-00.mp4"
    keep_thumb = tmp_path / "TK_alpha_2026.01.01_12-00-00.thumb.jpg"
    orphan = tmp_path / "TK_alpha_2026.01.01_13-00-00.thumb.jpg"
    orphan_temp = tmp_path / "TK_alpha_2026.01.01_14-00-00.thumb.tmp.jpg"
    keep_video.write_bytes(b"video")
    keep_thumb.write_bytes(b"jpeg")
    orphan.write_bytes(b"orphan-jpeg")
    orphan_temp.write_bytes(b"temp")

    deleted = purge_orphan_thumbnails([tmp_path])

    assert deleted == 2
    assert keep_thumb.is_file()
    assert not orphan.exists()
    assert not orphan_temp.exists()
