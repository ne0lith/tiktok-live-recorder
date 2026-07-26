import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from tiktok_live_recorder.core.tiktok_recorder import TikTokRecorder
from tiktok_live_recorder.utils.enums import Mode
from tiktok_live_recorder.utils.recorder_config import RecorderConfig
from tiktok_live_recorder.utils.utils import (
    add_user_to_file,
    read_paused_users,
    remove_user_from_file,
    write_paused_users,
)
from tiktok_live_recorder.web.app import create_app
from tiktok_live_recorder.web.media import resolve_media_path, scan_media_library


def test_add_user_preserves_array_format(tmp_path, monkeypatch):
    users_file = tmp_path / "users.json"
    users_file.write_text('["alpha"]', encoding="utf-8")
    add_user_to_file(str(users_file), "beta")
    data = json.loads(users_file.read_text(encoding="utf-8"))
    assert data == ["alpha", "beta"]


def test_add_user_preserves_object_format(tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text('{"users": ["alpha"]}', encoding="utf-8")
    add_user_to_file(str(users_file), "beta")
    data = json.loads(users_file.read_text(encoding="utf-8"))
    assert data == {"users": ["alpha", "beta"]}


def test_remove_user_preserves_object_format(tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text('{"users": ["alpha", "beta"]}', encoding="utf-8")
    users = remove_user_from_file(str(users_file), "alpha")
    data = json.loads(users_file.read_text(encoding="utf-8"))
    assert users == ["beta"]
    assert data == {"users": ["beta"]}


def test_paused_users_round_trip(tmp_path, monkeypatch):
    state_file = tmp_path / "watchlist_state.json"
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.utils.watchlist_state_path",
        lambda: str(state_file),
    )
    write_paused_users({"alpha", "beta"})
    assert read_paused_users() == {"alpha", "beta"}
    write_paused_users({"gamma"})
    assert read_paused_users() == {"gamma"}


def test_poll_users_once_skips_paused_users(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha", "beta"], cookies={})
    )
    recorder.tiktok = type(
        "API",
        (),
        {
            "get_room_id_from_user": lambda self, user: f"room-{user}",
            "is_room_alive": lambda self, room_id, user=None: True,
        },
    )()
    recorder._recording_worker = lambda *args, **kwargs: None
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.utils.read_paused_users",
        lambda: {"alpha"},
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    active = recorder._poll_users_once(["alpha", "beta"], {}, label="Watchlist")

    assert "alpha" not in active
    assert recorder._last_poll_snapshot["paused"] == ["alpha"]


def test_get_status_includes_recordings():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder._active_recordings = {
        "alpha": {
            "thread": None,
            "room_id": "room-alpha",
            "started_at": 1000.0,
            "output_path": "/tmp/alpha.mp4",
            "bytes_written": 4096,
            "status": "recording",
        }
    }
    recorder._last_poll_snapshot = {"offline": [], "recording": ["alpha"]}
    recorder._last_poll_at = 2000.0

    status = recorder.get_status()

    assert status["users"] == ["alpha"]
    assert status["recordings"][0]["username"] == "alpha"
    assert status["recordings"][0]["bytes_written"] == 4096
    assert status["use_telegram"] is False
    assert status["telegram_uploads"] == []
    assert status["poll_in_progress"] is False
    assert status["activity"] == []
    assert "ffmpeg" in status
    assert status["ffmpeg"]["source"] in {"vendor", "system", "custom", "missing"}


def test_get_status_omits_dead_finished_threads():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    dead_thread = MagicMock()
    dead_thread.is_alive.return_value = False
    recorder._active_recordings = {
        "alpha": {
            "thread": dead_thread,
            "room_id": "room-alpha",
            "started_at": 1000.0,
            "output_path": "/tmp/alpha.mp4",
            "bytes_written": 4096,
            "status": "finished",
        }
    }

    status = recorder.get_status()

    assert status["recordings"] == []


def test_scan_media_library_groups_by_username(tmp_path):
    import os

    user_dir = tmp_path / "alpha"
    user_dir.mkdir()
    older = user_dir / "TK_alpha_2026.01.01_12-00-00.mp4"
    newer = user_dir / "TK_alpha_2026.01.01_13-00-00.mp4"
    older.write_bytes(b"x" * 10)
    newer.write_bytes(b"y" * 20)
    os.utime(older, (1_000_000, 1_000_000))
    os.utime(newer, (2_000_000, 2_000_000))

    media = scan_media_library(tmp_path, None)

    assert list(media.keys()) == ["alpha"]
    assert len(media["alpha"]) == 2
    assert media["alpha"][0]["filename"].endswith("13-00-00.mp4")
    assert media["alpha"][0]["thumb_url"].endswith("/thumb")


def test_scan_media_library_includes_legacy_files(tmp_path):
    import os

    user_dir = tmp_path / "cri3_x"
    legacy_dir = user_dir / "legacy"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "2026-07-13_22-50-16_IMG_7691.mp4"
    legacy_file.write_bytes(b"x" * 10)
    os.utime(legacy_file, (2_000_000, 2_000_000))

    media = scan_media_library(tmp_path, None)

    assert list(media.keys()) == ["cri3_x"]
    assert len(media["cri3_x"]) == 1
    assert media["cri3_x"][0]["source"] == "legacy"
    assert media["cri3_x"][0]["url"] == (
        "/media/cri3_x/legacy/2026-07-13_22-50-16_IMG_7691.mp4"
    )
    assert media["cri3_x"][0]["thumb_url"] == (
        "/media/cri3_x/legacy/2026-07-13_22-50-16_IMG_7691.mp4/thumb"
    )


def test_resolve_media_path_serves_legacy_files(tmp_path):
    user_dir = tmp_path / "cri3_x" / "legacy"
    user_dir.mkdir(parents=True)
    file_path = user_dir / "2026-07-13_22-50-16_IMG_7691.mp4"
    file_path.write_bytes(b"legacy-video")

    resolved = resolve_media_path(
        tmp_path,
        None,
        "cri3_x",
        "2026-07-13_22-50-16_IMG_7691.mp4",
        subdir="legacy",
    )
    assert resolved == file_path.resolve()


def test_resolve_media_path_rejects_traversal(tmp_path):
    user_dir = tmp_path / "alpha"
    user_dir.mkdir()
    file_path = user_dir / "TK_alpha_2026.01.01_12-00-00.mp4"
    file_path.write_bytes(b"video")

    assert (
        resolve_media_path(
            tmp_path,
            None,
            "alpha",
            "../alpha/TK_alpha_2026.01.01_12-00-00.mp4",
        )
        is None
    )
    assert (
        resolve_media_path(tmp_path, None, "alpha", "TK_alpha_2026.01.01_12-00-00.mp4")
        == file_path.resolve()
    )


class StubRecorder:
    mode = Mode.WATCHLIST
    users = ["alpha"]
    users_file = None
    automatic_interval = 5
    use_telegram = False
    _telegram_uploads: list = []

    def get_status(self):
        return {
            "mode": "watchlist",
            "users": self.users,
            "paused": [],
            "recordings": [],
            "automatic_interval_minutes": self.automatic_interval,
            "use_telegram": self.use_telegram,
            "telegram_uploads": list(self._telegram_uploads),
            "poll": {},
            "poll_label": None,
            "last_poll_at": None,
            "poll_in_progress": getattr(self, "poll_in_progress", False),
            "activity": list(getattr(self, "activity", [])),
        }

    def active_recording_output_paths(self):
        return set(getattr(self, "_active_paths", ()))

    def get_convert_job(self):
        return None

    def get_ffmpeg_info(self):
        return {
            "path": "/usr/bin/ffmpeg",
            "source": "system",
            "version": "ffmpeg version 7.1.5",
            "hevc_capable": True,
            "hevc_probe": {"legacy": False, "enhanced": False, "roundtrip": True},
        }

    def start_pending_flv_converts(self):
        return {"running": False, "total": 0, "completed": 0, "failed": 0}

    def force_poll(self):
        self.polls = getattr(self, "polls", 0) + 1

    def stop_user(self, username):
        return username == "alpha"

    def reload_cookies(self):
        self.cookies_reloaded = True

    def update_runtime_settings(self, **kwargs):
        if kwargs.get("automatic_interval_minutes") is not None:
            self.automatic_interval = kwargs["automatic_interval_minutes"]
        if kwargs.get("use_telegram") is not None:
            self.use_telegram = kwargs["use_telegram"]
        return {
            "automatic_interval_minutes": self.automatic_interval,
            "use_telegram": self.use_telegram,
        }

    def start_recording_now(self, *, username=None, room_id=None):
        if username == "busy":
            raise RuntimeError("@busy is already recording")
        return {
            "username": username or "roomuser",
            "room_id": room_id or "room-1",
            "status": "started",
        }


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    recorder = StubRecorder()
    recorder.users_file = str(tmp_path / "users.json")
    (tmp_path / "users.json").write_text('{"users": ["alpha"]}', encoding="utf-8")
    config = RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.users_file_path",
        lambda: recorder.users_file,
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.scan_media_library",
        lambda *_args, **_kwargs: {},
    )
    client = TestClient(create_app(recorder, config))
    return client, recorder, tmp_path


def test_api_status(api_client):
    client, _, _ = api_client
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["users"] == ["alpha"]


def test_dashboard_index_cache_busts_assets(api_client):
    from tiktok_live_recorder.utils.version import get_version

    client, _, _ = api_client
    version = get_version()
    response = client.get("/")
    assert response.status_code == 200
    assert f"/style.css?v={version}" in response.text
    assert f"/js/boot.js?v={version}" in response.text
    assert 'data-version="' in response.text
    assert 'id="settings-modal"' in response.text
    assert 'id="logs-modal"' in response.text
    assert 'id="activity-feed"' in response.text
    assert 'id="connection-banner"' in response.text
    assert 'id="status-filter"' not in response.text
    assert 'id="startup-ffmpeg-data"' in response.text
    assert '"path":"/usr/bin/ffmpeg"' in response.text.replace(" ", "")
    assert "__FFMPEG_JSON__" not in response.text
    assert response.headers.get("cache-control") == "no-cache"


def test_api_events_route_registered(api_client):
    client, _, _ = api_client
    paths = {getattr(route, "path", None) for route in client.app.routes}
    assert "/api/events" in paths


def test_api_version(api_client):
    from tiktok_live_recorder.utils.version import get_version

    client, _, _ = api_client
    response = client.get("/api/version")
    assert response.status_code == 200
    assert response.json() == {"version": get_version()}


def test_api_add_remove_user(api_client):
    client, recorder, tmp_path = api_client
    response = client.post("/api/users", json={"username": "beta"})
    assert response.status_code == 200
    assert "beta" in response.json()["users"]
    assert json.loads((tmp_path / "users.json").read_text(encoding="utf-8")) == {
        "users": ["alpha", "beta"]
    }

    response = client.delete("/api/users/beta")
    assert response.status_code == 200
    assert recorder.polls >= 1


def test_api_pause_poll_and_stop(api_client, monkeypatch):
    client, recorder, tmp_path = api_client
    state_file = tmp_path / "watchlist_state.json"
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.utils.watchlist_state_path",
        lambda: str(state_file),
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.utils.read_paused_users",
        lambda: set(),
    )

    response = client.post("/api/users/alpha/pause")
    assert response.status_code == 200

    response = client.post("/api/poll")
    assert response.status_code == 200
    assert recorder.polls >= 1

    response = client.post("/api/recordings/alpha/stop")
    assert response.status_code == 200


def test_media_thumb_endpoint(tmp_path, monkeypatch):
    file_path = tmp_path / "TK_alpha_2026.01.01_12-00-00.mp4"
    thumb_path = tmp_path / "TK_alpha_2026.01.01_12-00-00.thumb.jpg"
    file_path.write_bytes(b"video-data")
    thumb_path.write_bytes(b"jpeg-data")

    recorder = StubRecorder()
    config = RecorderConfig(
        mode=Mode.WATCHLIST,
        users=["alpha"],
        cookies={},
        output=str(tmp_path),
    )
    client = TestClient(create_app(recorder, config))

    with monkeypatch.context() as patcher:
        patcher.setattr(
            "tiktok_live_recorder.web.app.ensure_thumbnail",
            lambda path, ffmpeg_path=None: thumb_path if path == file_path else None,
        )
        response = client.get("/media/alpha/TK_alpha_2026.01.01_12-00-00.mp4/thumb")

    assert response.status_code == 200
    assert response.content == b"jpeg-data"
    assert response.headers["content-type"].startswith("image/jpeg")


def test_media_range_response(tmp_path):
    file_path = tmp_path / "TK_alpha_2026.01.01_12-00-00.mp4"
    file_path.write_bytes(b"0123456789")

    recorder = StubRecorder()
    config = RecorderConfig(
        mode=Mode.WATCHLIST,
        users=["alpha"],
        cookies={},
        output=str(tmp_path),
    )
    client = TestClient(create_app(recorder, config))

    response = client.get(
        "/media/alpha/TK_alpha_2026.01.01_12-00-00.mp4",
        headers={"Range": "bytes=0-4"},
    )
    assert response.status_code in (200, 206)
    assert response.content[:5] == b"01234"


def test_legacy_media_range_response(tmp_path, monkeypatch):
    legacy_dir = tmp_path / "cri3_x" / "legacy"
    legacy_dir.mkdir(parents=True)
    file_path = legacy_dir / "2026-07-13_22-50-16_IMG_7691.mp4"
    file_path.write_bytes(b"0123456789")

    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.default_output_base",
        lambda: tmp_path,
    )

    recorder = StubRecorder()
    config = RecorderConfig(mode=Mode.WATCHLIST, users=["cri3_x"], cookies={})
    client = TestClient(create_app(recorder, config))

    response = client.get(
        "/media/cri3_x/legacy/2026-07-13_22-50-16_IMG_7691.mp4",
        headers={"Range": "bytes=0-4"},
    )
    assert response.status_code in (200, 206)
    assert response.content[:5] == b"01234"


def test_api_runtime_settings(api_client):
    client, recorder, _ = api_client
    response = client.get("/api/settings/runtime")
    assert response.status_code == 200
    payload = response.json()
    assert payload["automatic_interval_minutes"] == 5
    assert "ffmpeg" in payload
    assert payload["ffmpeg"]["source"] in {"vendor", "system", "custom", "missing"}

    response = client.put(
        "/api/settings/runtime",
        json={"automatic_interval_minutes": 10, "use_telegram": True},
    )
    assert response.status_code == 200
    assert recorder.automatic_interval == 10
    assert recorder.use_telegram is True


def test_api_ffmpeg(api_client):
    client, _, _ = api_client
    response = client.get("/api/ffmpeg")
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "/usr/bin/ffmpeg"
    assert payload["source"] in {"vendor", "system", "custom", "missing"}


def test_api_record_now(api_client):
    client, _, _ = api_client
    response = client.post("/api/record", json={"username": "beta"})
    assert response.status_code == 200
    assert response.json()["username"] == "beta"

    response = client.post("/api/record", json={})
    assert response.status_code == 400

    response = client.post("/api/record", json={"username": "busy"})
    assert response.status_code == 409


def test_api_delete_media(tmp_path):
    file_path = tmp_path / "TK_alpha_2026.01.01_12-00-00.mp4"
    file_path.write_bytes(b"video-data")
    in_progress = tmp_path / "TK_alpha_2026.01.01_13-00-00_flv.mp4"
    in_progress.write_bytes(b"partial")

    recorder = StubRecorder()
    recorder._active_paths = {str(in_progress.resolve())}
    config = RecorderConfig(
        mode=Mode.WATCHLIST,
        users=["alpha"],
        cookies={},
        output=str(tmp_path),
    )
    client = TestClient(create_app(recorder, config))

    response = client.delete("/api/media/alpha/TK_alpha_2026.01.01_12-00-00.mp4")
    assert response.status_code == 204
    assert not file_path.exists()

    response = client.delete("/api/media/alpha/TK_alpha_2026.01.01_13-00-00_flv.mp4")
    assert response.status_code == 400
    assert in_progress.exists()
