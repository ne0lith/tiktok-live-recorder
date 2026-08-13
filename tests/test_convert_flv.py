from pathlib import Path
from unittest.mock import patch

from tiktok_live_recorder.convert_flv import (
    convert_leftover_flv,
    is_leftover_flv_name,
    main,
)


def test_is_leftover_flv_name():
    assert is_leftover_flv_name("TK_creator_2026.08.11_23-46-40_flv.mp4")
    assert not is_leftover_flv_name("TK_creator_2026.08.11_23-46-40.mp4")
    assert not is_leftover_flv_name("2026-01-14_21-06-38_img_7064.mp4")


def test_convert_leftover_flv_rejects_non_flv_suffix():
    assert convert_leftover_flv("clip.mp4") is False


def test_convert_leftover_flv_calls_app_pipeline():
    with (
        patch(
            "tiktok_live_recorder.convert_flv.check_ffmpeg", return_value="ffmpeg"
        ) as check,
        patch(
            "tiktok_live_recorder.convert_flv.VideoManagement.convert_flv_to_mp4",
            return_value=True,
        ) as convert,
    ):
        assert convert_leftover_flv("TK_u_2026.01.01_00-00-00_flv.mp4") is True
        check.assert_called_once_with(None)
        convert.assert_called_once_with(
            "TK_u_2026.01.01_00-00-00_flv.mp4", ffmpeg_path="ffmpeg"
        )


def test_main_rejects_non_flv(capsys):
    assert main(["clip.mp4"]) == 2
    err = capsys.readouterr().err
    assert "not a leftover FLV" in err


def test_main_rejects_missing_file(tmp_path: Path, capsys):
    missing = tmp_path / "TK_u_2026.01.01_00-00-00_flv.mp4"
    assert main([str(missing)]) == 2
    assert "file not found" in capsys.readouterr().err


def test_main_converts_existing_flv(tmp_path: Path):
    flv = tmp_path / "TK_u_2026.01.01_00-00-00_flv.mp4"
    flv.write_bytes(b"x")
    with patch(
        "tiktok_live_recorder.convert_flv.convert_leftover_flv", return_value=True
    ) as convert:
        assert main(["--ffmpeg-path", "C:\\ffmpeg.exe", str(flv)]) == 0
        convert.assert_called_once_with(str(flv), ffmpeg_path="C:\\ffmpeg.exe")
