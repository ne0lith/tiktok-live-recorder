import pytest
from unittest.mock import patch

from tiktok_live_recorder.utils.custom_exceptions import FfmpegRequirementError
from tiktok_live_recorder.utils.ffmpeg_setup import (
    ARCH_ASSETS,
    build_enhanced_hevc_probe_flv,
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
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
    return_value=True,
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._probe_flv_bytes",
    return_value=True,
)
def test_ffmpeg_supports_legacy_hevc_flv_true(_mock_probe, _mock_sane, _mock_which):
    from tiktok_live_recorder.utils.ffmpeg_setup import ffmpeg_supports_legacy_hevc_flv

    assert ffmpeg_supports_legacy_hevc_flv("/usr/bin/ffmpeg") is True


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.shutil.which",
    return_value="/usr/bin/ffmpeg",
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
    return_value=True,
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._probe_flv_bytes",
    return_value=False,
)
def test_ffmpeg_supports_legacy_hevc_flv_false(_mock_probe, _mock_sane, _mock_which):
    from tiktok_live_recorder.utils.ffmpeg_setup import ffmpeg_supports_legacy_hevc_flv

    assert ffmpeg_supports_legacy_hevc_flv("/usr/bin/ffmpeg") is False


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.shutil.which",
    return_value="/usr/bin/ffmpeg",
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
    return_value=True,
)
@patch("tiktok_live_recorder.utils.ffmpeg_setup._probe_flv_bytes")
def test_ffmpeg_supports_legacy_hevc_flv_ffmpeg_inspect_fallback(
    mock_probe, _mock_sane, _mock_which
):
    from tiktok_live_recorder.utils.ffmpeg_setup import (
        build_legacy_hevc_probe_flv,
        ffmpeg_supports_legacy_hevc_flv,
    )

    mock_probe.side_effect = lambda _ffmpeg, flv: flv == build_legacy_hevc_probe_flv()
    assert ffmpeg_supports_legacy_hevc_flv("/usr/bin/ffmpeg") is True


def test_btbN_asset_names_are_n81_gpl():
    assert "n8.1" in ARCH_ASSETS["linux64"]
    assert "gpl" in ARCH_ASSETS["linux64"]
    assert "n7.1" not in ARCH_ASSETS["linux64"]


def test_ffprobe_for_resolves_sibling_next_to_vendor_ffmpeg(tmp_path):
    from tiktok_live_recorder.utils.ffmpeg_setup import ffprobe_for

    bin_dir = tmp_path / ".vendor" / "ffmpeg" / "n8.1-linux64" / "bin"
    bin_dir.mkdir(parents=True)
    ffmpeg_bin = bin_dir / "ffmpeg"
    ffprobe_bin = bin_dir / "ffprobe"
    ffmpeg_bin.write_text("", encoding="utf-8")
    ffprobe_bin.write_text("", encoding="utf-8")

    assert ffprobe_for(str(ffmpeg_bin)) == str(ffprobe_bin)


def test_ffprobe_for_does_not_rewrite_vendor_directory_segment(tmp_path):
    from tiktok_live_recorder.utils.ffmpeg_setup import ffprobe_for

    bin_dir = tmp_path / ".vendor" / "ffmpeg" / "n8.1-linux64" / "bin"
    bin_dir.mkdir(parents=True)
    ffmpeg_bin = bin_dir / "ffmpeg.exe"
    ffprobe_bin = bin_dir / "ffprobe.exe"
    ffmpeg_bin.write_text("", encoding="utf-8")
    ffprobe_bin.write_text("", encoding="utf-8")

    resolved = ffprobe_for(str(ffmpeg_bin))
    assert "ffprobe.exe" in resolved
    assert "/ffmpeg/" in resolved.replace("\\", "/") or "\\ffmpeg\\" in resolved

    path = vendor_ffmpeg_dir("linux64")
    assert path.parts[-3:] == (".vendor", "ffmpeg", "n8.1-linux64")


def test_build_enhanced_hevc_probe_flv_uses_hvc1_fourcc():
    legacy = build_legacy_hevc_probe_flv()
    enhanced = build_enhanced_hevc_probe_flv()
    assert legacy != enhanced
    assert b"hvc1" in enhanced
    assert b"hvc1" not in legacy


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.shutil.which",
    return_value="/usr/bin/ffmpeg",
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._verify_ffmpeg_hevc_roundtrip",
    return_value=False,
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
    return_value=True,
)
@patch("tiktok_live_recorder.utils.ffmpeg_setup._probe_flv_bytes")
def test_ffmpeg_hevc_capable_accepts_enhanced_probe_only(
    mock_probe, _mock_sane, _mock_roundtrip, _mock_which
):
    from tiktok_live_recorder.utils.ffmpeg_setup import ffmpeg_hevc_capable

    mock_probe.side_effect = lambda _ffmpeg, flv: flv == build_enhanced_hevc_probe_flv()
    assert ffmpeg_hevc_capable("/usr/bin/ffmpeg") is True


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.shutil.which",
    return_value="/usr/bin/ffmpeg",
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._verify_ffmpeg_hevc_roundtrip",
    return_value=True,
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
    return_value=True,
)
@patch("tiktok_live_recorder.utils.ffmpeg_setup._probe_flv_bytes", return_value=False)
def test_ffmpeg_hevc_capable_rejects_system_roundtrip_only(
    _mock_probe, _mock_sane, _mock_roundtrip, _mock_which
):
    from tiktok_live_recorder.utils.ffmpeg_setup import ffmpeg_hevc_capable

    assert ffmpeg_hevc_capable("/usr/bin/ffmpeg") is False


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.is_vendor_ffmpeg_path",
    return_value=True,
)
@patch("tiktok_live_recorder.utils.ffmpeg_setup.shutil.which", return_value=None)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
    return_value=True,
)
def test_ffmpeg_hevc_capable_trusts_vendor_without_probes(
    _mock_sane,
    _mock_which,
    _mock_vendor,
    tmp_path,
):
    from tiktok_live_recorder.utils.ffmpeg_setup import ffmpeg_hevc_capable

    ffmpeg_bin = tmp_path / "ffmpeg"
    ffmpeg_bin.write_text("", encoding="utf-8")
    assert ffmpeg_hevc_capable(str(ffmpeg_bin)) is True


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.shutil.which",
    return_value="/usr/bin/ffmpeg",
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._verify_ffmpeg_hevc_roundtrip",
    return_value=False,
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
    return_value=True,
)
@patch("tiktok_live_recorder.utils.ffmpeg_setup._probe_flv_bytes", return_value=False)
def test_ffmpeg_hevc_capable_rejects_when_all_probes_fail(
    _mock_probe, _mock_sane, _mock_roundtrip, _mock_which
):
    from tiktok_live_recorder.utils.ffmpeg_setup import ffmpeg_hevc_capable

    assert ffmpeg_hevc_capable("/usr/bin/ffmpeg") is False


@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.is_vendor_ffmpeg_path",
    return_value=True,
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
    return_value=True,
)
def test_probe_ffmpeg_hevc_flv_skips_probes_for_vendor(_mock_sane, _mock_vendor):
    from tiktok_live_recorder.utils.ffmpeg_setup import probe_ffmpeg_hevc_flv

    assert probe_ffmpeg_hevc_flv("/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg") == {
        "legacy": False,
        "enhanced": False,
        "roundtrip": False,
    }


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
@patch("tiktok_live_recorder.utils.dependencies.describe_ffmpeg_binary")
@patch("tiktok_live_recorder.utils.dependencies.log_ffmpeg_status")
@patch("tiktok_live_recorder.utils.dependencies.shutil.which", return_value=None)
def test_check_ffmpeg_linux_vendor_install_when_missing(
    _mock_which,
    _mock_log_status,
    mock_describe,
    mock_resolve,
    _mock_platform,
):
    from tiktok_live_recorder.utils.dependencies import check_ffmpeg

    mock_describe.return_value = {
        "path": "/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg",
        "source": "vendor",
        "version": "ffmpeg version 8.1",
        "hevc_capable": True,
        "hevc_probe": {"legacy": True, "enhanced": True, "roundtrip": True},
    }

    result = check_ffmpeg()

    assert result == "/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg"
    mock_resolve.assert_called_once_with(None)
    mock_describe.assert_called_once_with(
        "/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg"
    )


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
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._trusted_vendor_ffmpeg",
    return_value=None,
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.install_linux_vendor_ffmpeg",
    return_value="/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg",
)
def test_resolve_ffmpeg_path_linux_installs_vendor(
    mock_install,
    _mock_trusted,
    _mock_platform,
):
    from tiktok_live_recorder.utils.ffmpeg_setup import resolve_ffmpeg_path

    assert resolve_ffmpeg_path() == "/repo/.vendor/ffmpeg/n8.1-linux64/bin/ffmpeg"
    mock_install.assert_called_once()


@patch("platform.system", return_value="Linux")
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.shutil.which",
    return_value="/usr/bin/ffmpeg",
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._verify_ffmpeg_hevc_roundtrip",
    return_value=True,
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
    return_value=True,
)
@patch("tiktok_live_recorder.utils.ffmpeg_setup._probe_flv_bytes", return_value=False)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.install_linux_vendor_ffmpeg",
    side_effect=RuntimeError("network down"),
)
def test_resolve_ffmpeg_path_linux_raises_when_vendor_install_fails(
    _mock_install,
    _mock_probe,
    _mock_sane,
    _mock_roundtrip,
    _mock_which,
    _mock_platform,
):
    from tiktok_live_recorder.utils.custom_exceptions import FfmpegRequirementError
    from tiktok_live_recorder.utils.ffmpeg_setup import resolve_ffmpeg_path

    with pytest.raises(FfmpegRequirementError, match="network down"):
        resolve_ffmpeg_path()


@patch("platform.system", return_value="Linux")
@patch(
    "tiktok_live_recorder.utils.dependencies.resolve_ffmpeg_path",
    side_effect=FfmpegRequirementError("network down"),
)
def test_check_ffmpeg_linux_raises_when_vendor_install_fails(
    _mock_resolve,
    _mock_platform,
):
    from tiktok_live_recorder.utils.custom_exceptions import FfmpegRequirementError
    from tiktok_live_recorder.utils.dependencies import check_ffmpeg

    with pytest.raises(FfmpegRequirementError, match="network down"):
        check_ffmpeg()


def test_trusted_vendor_ffmpeg_uses_installed_binary_without_probes(tmp_path):
    from tiktok_live_recorder.utils.ffmpeg_setup import (
        _trusted_vendor_ffmpeg,
        describe_ffmpeg_binary,
    )

    arch_key = "linux64"
    install_dir = tmp_path / ".vendor" / "ffmpeg" / "n8.1-linux64"
    bin_dir = install_dir / "bin"
    bin_dir.mkdir(parents=True)
    ffmpeg_bin = bin_dir / "ffmpeg"
    ffprobe_bin = bin_dir / "ffprobe"
    ffmpeg_bin.write_text("", encoding="utf-8")
    ffprobe_bin.write_text("", encoding="utf-8")

    with (
        patch(
            "tiktok_live_recorder.utils.ffmpeg_setup.vendor_ffmpeg_dir",
            return_value=install_dir,
        ),
        patch(
            "tiktok_live_recorder.utils.ffmpeg_setup._ffmpeg_install_sane",
            return_value=True,
        ),
        patch(
            "tiktok_live_recorder.utils.ffmpeg_setup.verify_installed_ffmpeg"
        ) as mock_verify,
    ):
        path = _trusted_vendor_ffmpeg(arch_key)
        info = describe_ffmpeg_binary(str(ffmpeg_bin))

    assert path == str(ffmpeg_bin)
    mock_verify.assert_not_called()
    assert info["hevc_capable"] is True
    assert info["source"] == "vendor"
    assert info["hevc_probe"] is None


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
    "tiktok_live_recorder.utils.ffmpeg_setup.verify_installed_ffmpeg",
    return_value=(True, {"legacy": True, "enhanced": True, "roundtrip": True}),
)
@patch(
    "tiktok_live_recorder.utils.ffmpeg_setup.ffmpeg_version_line",
    return_value="ffmpeg version 8.1",
)
def test_describe_ffmpeg_binary_reports_capability(
    _mock_version, _mock_probe, tmp_path
):
    from tiktok_live_recorder.utils.ffmpeg_setup import describe_ffmpeg_binary

    ffmpeg_bin = tmp_path / "ffmpeg"
    ffmpeg_bin.write_text("", encoding="utf-8")
    info = describe_ffmpeg_binary(str(ffmpeg_bin))
    assert info["hevc_capable"] is True
    assert info["hevc_probe"] == {
        "legacy": True,
        "enhanced": True,
        "roundtrip": True,
    }
    assert info["version"] == "ffmpeg version 8.1"
    assert info["source"] == "custom"


def test_progress_percent_clamps_to_ninety_nine_until_done():
    from tiktok_live_recorder.utils.video_management import VideoManagement

    assert VideoManagement.progress_percent(1_500_000_000, 3600.0) == 41
    assert VideoManagement.progress_percent(4_000_000_000, 3600.0) == 99
