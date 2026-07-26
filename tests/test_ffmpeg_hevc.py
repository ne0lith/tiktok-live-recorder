import pytest
from unittest.mock import MagicMock, patch

from tiktok_live_recorder.utils.ffmpeg_setup import (
    ARCH_ASSETS,
    build_legacy_hevc_probe_flv,
    normalize_cdn_url,
    vendor_ffmpeg_dir,
)
from tiktok_live_recorder.utils.flv_hevc_rewrite import (
    file_needs_legacy_hevc_rewrite,
    rewrite_legacy_hevc_video_body,
)
from tiktok_live_recorder.web.media import find_orphan_flv_files, scan_media_library


def test_normalize_cdn_url_strips_signed_query():
    url = "https://pull-flv.example.com/stream_hd.flv?expire=123&sign=abc&only_audio=0"
    assert normalize_cdn_url(url) == "https://pull-flv.example.com/stream_hd.flv"


def test_rewrite_legacy_hevc_sequence_start_to_hvc1():
    body = bytes([0x1C, 0x00, 0xAA, 0xBB, 0xCC])
    rewritten = rewrite_legacy_hevc_video_body(body)
    assert rewritten[0] & 0x0F == 0
    assert rewritten[1:5] == b"hvc1"
    assert rewritten[5:] == body[2:]


def test_rewrite_legacy_hevc_nalu_to_hvc1():
    body = bytes([0x2C, 0x01, 0x00, 0x01, 0x02, 0xDE, 0xAD])
    rewritten = rewrite_legacy_hevc_video_body(body)
    assert rewritten[0] & 0x0F == 1
    assert rewritten[1:5] == b"hvc1"
    assert rewritten[5:8] == body[2:5]
    assert rewritten[8:] == body[5:]


def test_file_needs_legacy_hevc_rewrite_detects_codec_12(tmp_path):
    flv_path = tmp_path / "test.flv"
    flv_path.write_bytes(build_legacy_hevc_probe_flv())
    assert file_needs_legacy_hevc_rewrite(flv_path) is True


def test_find_orphan_flv_files_skips_active(tmp_path):
    user_dir = tmp_path / "goat__spitt"
    user_dir.mkdir()
    orphan = user_dir / "TK_goat__spitt_2026.07.26_13-27-20_flv.mp4"
    orphan.write_bytes(b"data")
    active = user_dir / "TK_goat__spitt_2026.07.26_14-00-00_flv.mp4"
    active.write_bytes(b"live")

    orphans = find_orphan_flv_files(tmp_path, None, {str(orphan.resolve())})
    names = [item["filename"] for item in orphans]
    assert "TK_goat__spitt_2026.07.26_14-00-00_flv.mp4" in names
    assert "TK_goat__spitt_2026.07.26_13-27-20_flv.mp4" not in names


def test_scan_media_library_marks_needs_convert(tmp_path):
    user_dir = tmp_path / "creator"
    user_dir.mkdir()
    flv = user_dir / "TK_creator_2026.07.26_12-00-00_flv.mp4"
    flv.write_bytes(b"x")
    media = scan_media_library(tmp_path, None, active_output_paths=set())
    entry = media["creator"][0]
    assert entry["needs_convert"] is True
    assert entry["in_progress"] is False


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.shutil.which",
    return_value="/usr/bin/ffmpeg",
)
@patch("tiktok_live_recorder.utils.ffmpeg_setup.subprocess.run")
def test_ffmpeg_supports_legacy_hevc_flv_true(mock_run, _mock_which):
    mock_run.return_value = MagicMock(returncode=0, stdout="hevc\n", stderr="")
    from tiktok_live_recorder.utils.ffmpeg_setup import ffmpeg_supports_legacy_hevc_flv

    assert ffmpeg_supports_legacy_hevc_flv("/usr/bin/ffmpeg") is True


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.shutil.which",
    return_value="/usr/bin/ffmpeg",
)
@patch("tiktok_live_recorder.utils.ffmpeg_setup.subprocess.run")
def test_ffmpeg_supports_legacy_hevc_flv_false(mock_run, _mock_which):
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="Video codec (c) is not implemented",
    )
    from tiktok_live_recorder.utils.ffmpeg_setup import ffmpeg_supports_legacy_hevc_flv

    assert ffmpeg_supports_legacy_hevc_flv("/usr/bin/ffmpeg") is False


def test_btbN_asset_names_are_n81_gpl():
    assert "n8.1" in ARCH_ASSETS["linux64"]
    assert "gpl" in ARCH_ASSETS["linux64"]
    assert "n7.1" not in ARCH_ASSETS["linux64"]


def test_vendor_ffmpeg_dir_under_repo():
    path = vendor_ffmpeg_dir("linux64")
    assert path.parts[-3:] == (".vendor", "ffmpeg", "n8.1-linux64")


def test_pick_next_stream_url_uses_normalized_identity():
    from tiktok_live_recorder.core.tiktok_recorder import TikTokRecorder
    from tiktok_live_recorder.utils.recorder_config import RecorderConfig
    from tiktok_live_recorder.utils.enums import Mode

    recorder = TikTokRecorder(RecorderConfig(mode=Mode.WATCHLIST, cookies={}))
    failed = {normalize_cdn_url("https://cdn.example.com/a.flv?sign=1")}
    candidates = ["https://cdn.example.com/a.flv?sign=2"]
    assert recorder._pick_next_stream_url(candidates, failed) is None


def test_convert_flv_to_mp4_returns_false_when_locked(tmp_path):
    from tiktok_live_recorder.utils.video_management import VideoManagement

    flv = tmp_path / "TK_user_2026.07.26_12-00-00_flv.mp4"
    flv.write_bytes(b"x")
    with patch.object(VideoManagement, "wait_for_file_release", return_value=False):
        assert VideoManagement.convert_flv_to_mp4(str(flv)) is False


@patch("platform.system", return_value="Linux")
@patch(
    "tiktok_live_recorder.utils.dependencies.resolve_ffmpeg_path",
    return_value="/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg",
)
@patch("tiktok_live_recorder.utils.dependencies.log_ffmpeg_status")
@patch("tiktok_live_recorder.utils.dependencies.shutil.which", return_value=None)
def test_check_ffmpeg_linux_vendor_install_when_missing(
    _mock_which,
    _mock_log_status,
    mock_resolve,
    _mock_platform,
):
    from tiktok_live_recorder.utils.dependencies import check_ffmpeg

    result = check_ffmpeg()

    assert result == "/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg"
    mock_resolve.assert_called_once_with(None)


@patch("platform.system", return_value="Windows")
@patch(
    "tiktok_live_recorder.utils.dependencies.install_ffmpeg_binary",
    side_effect=SystemExit(1),
)
@patch("tiktok_live_recorder.utils.dependencies.shutil.which", return_value=None)
def test_check_ffmpeg_non_linux_exits_when_missing(
    _mock_which,
    _mock_install,
    _mock_platform,
):
    from tiktok_live_recorder.utils.dependencies import check_ffmpeg

    with pytest.raises(SystemExit):
        check_ffmpeg()


@patch("platform.system", return_value="Linux")
@patch("tiktok_live_recorder.utils.ffmpeg_setup.shutil.which", return_value=None)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.install_linux_vendor_ffmpeg",
    return_value="/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg",
)
def test_resolve_ffmpeg_path_linux_installs_with_no_candidates(
    mock_install,
    _mock_which,
    _mock_platform,
):
    from tiktok_live_recorder.utils.ffmpeg_setup import resolve_ffmpeg_path

    assert resolve_ffmpeg_path() == "/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg"
    mock_install.assert_called_once()


def test_parse_ffmpeg_progress_line_reads_out_time_us():
    from tiktok_live_recorder.utils.video_management import VideoManagement

    assert VideoManagement.parse_ffmpeg_progress_line("out_time_us=1500000") == {
        "out_time_us": 1500000
    }
    assert VideoManagement.parse_ffmpeg_progress_line("progress=continue") == {
        "progress": "continue"
    }


def test_describe_ffmpeg_binary_detects_vendor_path():
    from tiktok_live_recorder.utils.ffmpeg_setup import describe_ffmpeg_binary

    info = describe_ffmpeg_binary("/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg")
    assert info["source"] == "vendor"
    assert ".vendor" in info["path"]


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.ffmpeg_supports_legacy_hevc_flv",
    return_value=True,
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.ffmpeg_version_line",
    return_value="ffmpeg version 8.1",
)
def test_describe_ffmpeg_binary_reports_capability(
    _mock_version, _mock_capable, tmp_path
):
    from tiktok_live_recorder.utils.ffmpeg_setup import describe_ffmpeg_binary

    ffmpeg_bin = tmp_path / "ffmpeg"
    ffmpeg_bin.write_text("", encoding="utf-8")
    info = describe_ffmpeg_binary(str(ffmpeg_bin))
    assert info["hevc_capable"] is True
    assert info["version"] == "ffmpeg version 8.1"
    assert info["source"] == "custom"


def test_progress_percent_clamps_to_ninety_nine_until_done():
    from tiktok_live_recorder.utils.video_management import VideoManagement

    assert VideoManagement.progress_percent(1_500_000_000, 3600.0) == 41
    assert VideoManagement.progress_percent(4_000_000_000, 3600.0) == 99
