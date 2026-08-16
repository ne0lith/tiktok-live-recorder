from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tiktok_live_recorder.utils.enums import Mode
from tiktok_live_recorder.utils.recorder_config import RecorderConfig
from tiktok_live_recorder.utils.video_management import VideoManagement
from tiktok_live_recorder.web.app import create_app
from tiktok_live_recorder.web.codec_index import (
    INDEX_FILENAME,
    configure_codec_index,
    get_codec_index,
    reset_codec_index,
)
from tiktok_live_recorder.web.media import (
    clear_library_playable_cache,
    scan_media_inventory,
    scan_media_library,
)


@pytest.fixture(autouse=True)
def _reset_codec_index():
    clear_library_playable_cache()
    yield
    clear_library_playable_cache()


def _write_clip(user_dir: Path, name: str, data: bytes = b"clip") -> Path:
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / name
    path.write_bytes(data)
    return path


def _patch_probe(monkeypatch, mapping: dict[str, tuple[str, str]] | tuple[str, str]):
    calls: list[str] = []

    def fake_probe(input_file: str, _ffprobe_cmd: str) -> tuple[str, str]:
        calls.append(input_file)
        if isinstance(mapping, tuple):
            return mapping
        return mapping.get(Path(input_file).name, ("h264", "yuv420p"))

    monkeypatch.setattr(
        VideoManagement,
        "_probe_video_info",
        staticmethod(fake_probe),
    )
    return calls


def test_scan_media_inventory_includes_codec_and_busy_rows(tmp_path, monkeypatch):
    user_dir = tmp_path / "alpha"
    finished = _write_clip(user_dir, "TK_alpha_2026.01.01_12-00-00.mp4")
    av1 = _write_clip(user_dir, "TK_alpha_2026.01.01_12-30-00.mp4", b"av1")
    orphan_flv = _write_clip(
        user_dir, "TK_alpha_2026.01.01_14-00-00_flv.mp4", b"orphan"
    )
    active_flv = _write_clip(
        user_dir, "TK_alpha_2026.01.01_13-00-00_flv.mp4", b"partial"
    )
    converting_mp4 = _write_clip(
        user_dir, "TK_alpha_2026.01.01_13-00-00.mp4", b"incomplete"
    )
    with_temp = _write_clip(user_dir, "TK_alpha_2026.01.01_15-00-00.mp4")
    av1_temp = user_dir / "TK_alpha_2026.01.01_15-00-00.av1temp.mp4"
    av1_temp.write_bytes(b"tmp")
    live = _write_clip(user_dir, "TK_alpha_2026.01.01_16-00-00_flv.mp4", b"live")
    queued_src = _write_clip(user_dir, "TK_alpha_2026.01.01_17-00-00_flv.mp4", b"q")
    repair_tmp = user_dir / "TK_alpha_2026.01.01_12-00-00.repair.tmp.mp4"
    repair_tmp.write_bytes(b"tmp")

    _patch_probe(
        monkeypatch,
        {
            finished.name: ("h264", "yuv420p"),
            av1.name: ("av1", "yuv420p"),
            orphan_flv.name: ("hevc", "yuv420p"),
            with_temp.name: ("h264", "yuv420p"),
        },
    )

    videos = scan_media_inventory(
        tmp_path,
        None,
        active_output_paths={
            str(active_flv.resolve()),
            str(live.resolve()),
            str(queued_src.resolve()),
        },
        media_jobs=[
            {"path": str(active_flv.resolve()), "status": "converting"},
            {"path": str(queued_src.resolve()), "status": "queued"},
        ],
    )
    by_name = {item["filename"]: item for item in videos}

    assert repair_tmp.name not in by_name
    assert av1_temp.name not in by_name
    assert by_name[finished.name]["codec"] == "h264"
    assert by_name[finished.name]["is_av1"] is False
    assert by_name[finished.name]["in_progress"] is False
    assert by_name[finished.name]["converting"] is False
    assert by_name[finished.name]["busy_reason"] is None
    assert by_name[av1.name]["is_av1"] is True
    assert by_name[orphan_flv.name]["needs_convert"] is True
    assert by_name[orphan_flv.name]["codec"] == "hevc"
    assert by_name[active_flv.name]["in_progress"] is True
    assert by_name[active_flv.name]["converting"] is True
    assert by_name[active_flv.name]["busy_reason"] == "converting"
    assert by_name[converting_mp4.name]["in_progress"] is True
    assert by_name[live.name]["in_progress"] is True
    assert by_name[live.name]["converting"] is False
    assert by_name[live.name]["busy_reason"] == "recording"
    assert by_name[queued_src.name]["converting"] is True
    assert by_name[queued_src.name]["busy_reason"] == "queued"
    assert by_name[with_temp.name]["converting"] is True
    assert by_name[with_temp.name]["busy_reason"] == "av1temp"
    assert by_name[with_temp.name]["codec"] == "h264"

    ready = scan_media_inventory(
        tmp_path,
        None,
        active_output_paths={
            str(active_flv.resolve()),
            str(live.resolve()),
            str(queued_src.resolve()),
        },
        media_jobs=[
            {"path": str(active_flv.resolve()), "status": "converting"},
            {"path": str(queued_src.resolve()), "status": "queued"},
        ],
        ready=True,
    )
    ready_names = {item["filename"] for item in ready}
    assert ready_names == {finished.name}
    assert all(item["is_av1"] is False for item in ready)
    assert all(not item["in_progress"] and not item["converting"] for item in ready)


def test_codec_index_hit_skips_ffprobe(tmp_path, monkeypatch):
    user_dir = tmp_path / "alpha"
    clip = _write_clip(user_dir, "TK_alpha_2026.01.01_12-00-00.mp4")
    calls = _patch_probe(monkeypatch, ("h264", "yuv420p"))

    scan_media_inventory(tmp_path, None)
    assert calls == [str(clip.resolve())]
    scan_media_inventory(tmp_path, None)
    assert calls == [str(clip.resolve())]


def test_codec_index_mtime_size_change_reprobes(tmp_path, monkeypatch):
    user_dir = tmp_path / "alpha"
    clip = _write_clip(user_dir, "TK_alpha_2026.01.01_12-00-00.mp4")
    calls = _patch_probe(monkeypatch, ("h264", "yuv420p"))

    scan_media_inventory(tmp_path, None)
    clip.write_bytes(b"replaced-av1-bytes")
    monkeypatch.setattr(
        VideoManagement,
        "_probe_video_info",
        staticmethod(
            lambda input_file, _cmd, _calls=calls: (
                _calls.append(input_file) or ("av1", "yuv420p")
            )
        ),
    )
    videos = scan_media_inventory(tmp_path, None)
    assert len(calls) == 2
    assert videos[0]["is_av1"] is True


def test_av1temp_appear_does_not_reprobe(tmp_path, monkeypatch):
    user_dir = tmp_path / "alpha"
    clip = _write_clip(user_dir, "TK_alpha_2026.01.01_12-00-00.mp4")
    calls = _patch_probe(monkeypatch, ("h264", "yuv420p"))

    first = scan_media_inventory(tmp_path, None)
    assert first[0]["converting"] is False
    (user_dir / "TK_alpha_2026.01.01_12-00-00.av1temp.mp4").write_bytes(b"tmp")
    second = scan_media_inventory(tmp_path, None)
    assert calls == [str(clip.resolve())]
    assert second[0]["converting"] is True
    assert second[0]["busy_reason"] == "av1temp"
    assert second[0]["codec"] == "h264"


def test_av1temp_disappear_force_reprobes_even_if_stat_matches(tmp_path, monkeypatch):
    user_dir = tmp_path / "alpha"
    _write_clip(user_dir, "TK_alpha_2026.01.01_12-00-00.mp4")
    temp = user_dir / "TK_alpha_2026.01.01_12-00-00.av1temp.mp4"
    temp.write_bytes(b"tmp")
    calls = _patch_probe(monkeypatch, ("h264", "yuv420p"))

    first = scan_media_inventory(tmp_path, None)
    assert first[0]["busy_reason"] == "av1temp"
    temp.unlink()
    probe_state = {"n": 0}

    def after_replace(input_file: str, _cmd: str) -> tuple[str, str]:
        calls.append(input_file)
        probe_state["n"] += 1
        return ("av1", "yuv420p")

    monkeypatch.setattr(
        VideoManagement, "_probe_video_info", staticmethod(after_replace)
    )
    second = scan_media_inventory(tmp_path, None)
    assert probe_state["n"] == 1
    assert second[0]["is_av1"] is True
    assert second[0]["converting"] is False


def test_codec_index_round_trip_survives_reset(tmp_path, monkeypatch):
    user_dir = tmp_path / "alpha"
    clip = _write_clip(user_dir, "TK_alpha_2026.01.01_12-00-00.mp4")
    calls = _patch_probe(monkeypatch, ("h264", "yuv420p"))
    scan_media_inventory(tmp_path, None)
    assert (tmp_path / INDEX_FILENAME).is_file()
    reset_codec_index()
    configure_codec_index(tmp_path, None)
    videos = scan_media_inventory(tmp_path, None)
    assert calls == [str(clip.resolve())]
    assert videos[0]["codec"] == "h264"


def test_codec_index_prunes_deleted_files(tmp_path, monkeypatch):
    user_dir = tmp_path / "alpha"
    keep = _write_clip(user_dir, "TK_alpha_2026.01.01_12-00-00.mp4")
    gone = _write_clip(user_dir, "TK_alpha_2026.01.01_13-00-00.mp4")
    _patch_probe(monkeypatch, ("h264", "yuv420p"))
    scan_media_inventory(tmp_path, None)
    gone.unlink()
    scan_media_inventory(tmp_path, None)
    index = get_codec_index()
    assert str(keep.resolve()) in index._entries
    assert str(gone.resolve()) not in index._entries


def test_dashboard_scan_still_hides_in_progress(tmp_path, monkeypatch):
    user_dir = tmp_path / "alpha"
    finished = _write_clip(user_dir, "TK_alpha_2026.01.01_12-00-00.mp4")
    active = _write_clip(user_dir, "TK_alpha_2026.01.01_13-00-00_flv.mp4", b"partial")
    _patch_probe(monkeypatch, ("h264", "yuv420p"))
    media = scan_media_library(
        tmp_path, None, active_output_paths={str(active.resolve())}
    )
    names = {entry["filename"] for entry in media["alpha"]}
    assert finished.name in names
    assert active.name not in names
    assert "codec" not in media["alpha"][0]


def test_api_media_inventory_ready_filter(tmp_path, monkeypatch):
    user_dir = tmp_path / "alpha"
    h264 = _write_clip(user_dir, "TK_alpha_2026.01.01_12-00-00.mp4")
    av1 = _write_clip(user_dir, "TK_alpha_2026.01.01_13-00-00.mp4", b"av1")
    _patch_probe(
        monkeypatch,
        {
            h264.name: ("h264", "yuv420p"),
            av1.name: ("av1", "yuv420p"),
        },
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.default_output_base",
        lambda: tmp_path,
    )

    class Recorder:
        mode = Mode.WATCHLIST
        users = ["alpha"]
        users_file = str(tmp_path / "users.json")
        automatic_interval = 5
        use_telegram = False
        use_identity_tracking = False
        auto_update_when_idle = False
        max_concurrent_converts = 1
        _telegram_uploads: list = []
        ffmpeg_path = None

        def get_status(self):
            return {"users": self.users}

        def active_recording_output_paths(self):
            return set()

        def _media_jobs_snapshot(self):
            return []

        def get_ffmpeg_info(self):
            return {"path": "/usr/bin/ffmpeg", "source": "system"}

    (tmp_path / "users.json").write_text('{"users": ["alpha"]}', encoding="utf-8")
    config = RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    client = TestClient(create_app(Recorder(), config))

    full = client.get("/api/media/inventory")
    assert full.status_code == 200
    payload = full.json()
    assert payload["ready"] is False
    assert payload["count"] == 2
    assert {item["filename"] for item in payload["videos"]} == {h264.name, av1.name}

    ready = client.get("/api/media/inventory", params={"ready": True})
    assert ready.status_code == 200
    cut = ready.json()
    assert cut["ready"] is True
    assert cut["count"] == 1
    assert cut["videos"][0]["filename"] == h264.name
    assert "no-store" in full.headers.get("cache-control", "").lower()
