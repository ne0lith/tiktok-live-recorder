import json
from pathlib import Path
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

    active, _ = recorder._poll_users_once(["alpha", "beta"], {}, label="Watchlist")

    assert "alpha" not in active
    assert recorder._last_poll_snapshot["paused"] == ["alpha"]


def test_get_status_includes_recordings():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    alive_thread = MagicMock()
    alive_thread.is_alive.return_value = True
    recorder._active_recordings = {
        "alpha": {
            "thread": alive_thread,
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


def test_get_status_excludes_convert_from_recordings_list():
    """Convert no longer occupies the per-user recording slot."""
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
            "output_path": "/tmp/alpha_flv.mp4",
            "bytes_written": 4096,
            "status": "convert_queued",
        }
    }
    recorder._media_jobs["/tmp/alpha_flv.mp4"] = {
        "username": "alpha",
        "filename": "alpha_flv.mp4",
        "mode": "flv",
        "status": "queued",
        "queue_position": 99,  # stale — snapshot must recompute
        "queued_at": 1000.0,
    }

    status = recorder.get_status()

    assert status["recordings"] == []
    assert len(status["media_jobs"]) == 1
    assert status["media_jobs"][0]["status"] == "queued"
    assert status["media_jobs"][0]["username"] == "alpha"
    assert status["media_jobs"][0]["queue_position"] == 1
    assert status["convert_queue"]["max_concurrent"] == 1


def test_media_jobs_snapshot_assigns_unique_live_queue_positions():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha", "beta"], cookies={})
    )
    recorder._media_jobs = {
        "/tmp/a_flv.mp4": {
            "username": "alpha",
            "filename": "a_flv.mp4",
            "mode": "flv",
            "status": "queued",
            "queue_position": 5,
            "queued_at": 100.0,
        },
        "/tmp/b_flv.mp4": {
            "username": "beta",
            "filename": "b_flv.mp4",
            "mode": "flv",
            "status": "converting",
            "queue_position": 1,
            "queued_at": 50.0,
            "convert_progress": {"percent": 10, "queue_position": 1},
        },
        "/tmp/c_flv.mp4": {
            "username": "gamma",
            "filename": "c_flv.mp4",
            "mode": "flv",
            "status": "queued",
            "queue_position": 5,
            "queued_at": 200.0,
        },
    }

    jobs = recorder._media_jobs_snapshot()
    by_path = {job["path"]: job for job in jobs}

    assert by_path["/tmp/b_flv.mp4"]["status"] == "converting"
    assert "queue_position" not in by_path["/tmp/b_flv.mp4"]
    assert "queue_position" not in (
        by_path["/tmp/b_flv.mp4"].get("convert_progress") or {}
    )

    assert by_path["/tmp/a_flv.mp4"]["queue_position"] == 1
    assert by_path["/tmp/c_flv.mp4"]["queue_position"] == 2
    assert by_path["/tmp/a_flv.mp4"]["convert_progress"]["queue_position"] == 1
    assert by_path["/tmp/c_flv.mp4"]["convert_progress"]["queue_position"] == 2
    # Converting jobs sort first, then waiting in FIFO order.
    assert [job["path"] for job in jobs] == [
        "/tmp/b_flv.mp4",
        "/tmp/a_flv.mp4",
        "/tmp/c_flv.mp4",
    ]


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


def test_scan_media_library_purges_orphan_thumbnails(tmp_path):
    user_dir = tmp_path / "alpha"
    user_dir.mkdir()
    video = user_dir / "TK_alpha_2026.01.01_12-00-00.mp4"
    keep_thumb = user_dir / "TK_alpha_2026.01.01_12-00-00.thumb.jpg"
    orphan = user_dir / "TK_alpha_2026.01.01_13-00-00.thumb.jpg"
    video.write_bytes(b"video")
    keep_thumb.write_bytes(b"keep")
    orphan.write_bytes(b"orphan")

    media = scan_media_library(tmp_path, None)

    assert list(media.keys()) == ["alpha"]
    assert keep_thumb.is_file()
    assert not orphan.exists()


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


def test_resolve_media_path_allows_embedded_dots_in_username(tmp_path):
    """TikTok usernames with embedded '..' must remain playable in the media library."""
    username = "creator..99"
    user_dir = tmp_path / username
    user_dir.mkdir()
    filename = f"TK_{username}_2026.08.04_14-12-57.mp4"
    file_path = user_dir / filename
    file_path.write_bytes(b"video")

    assert resolve_media_path(tmp_path, None, username, filename) == file_path.resolve()

    from tiktok_live_recorder.web.media import scan_media_library

    library = scan_media_library(tmp_path, None)
    assert username in library
    assert library[username][0]["filename"] == filename
    assert filename in library[username][0]["url"]
    assert library[username][0]["thumb_url"].endswith("/thumb")


@pytest.mark.parametrize(
    "username",
    [
        "_creator",
        "_.user.99",
        "__user_name_",
        "user__name",
    ],
)
def test_resolve_media_path_allows_underscores_in_username(tmp_path, username):
    """Usernames with leading/embedded '_' must match MEDIA_PATTERN and resolve."""
    from tiktok_live_recorder.web.media import MEDIA_PATTERN, scan_media_library

    user_dir = tmp_path / username
    user_dir.mkdir()
    filename = f"TK_{username}_2026.08.05_11-05-17.mp4"
    file_path = user_dir / filename
    file_path.write_bytes(b"video")

    match = MEDIA_PATTERN.match(filename)
    assert match is not None
    assert match.group("username") == username
    assert resolve_media_path(tmp_path, None, username, filename) == file_path.resolve()

    library = scan_media_library(tmp_path, None)
    assert username in library
    assert library[username][0]["filename"] == filename
    assert library[username][0]["thumb_url"].endswith("/thumb")


class StubRecorder:
    mode = Mode.WATCHLIST
    users = ["alpha"]
    users_file = None
    automatic_interval = 5
    use_telegram = False
    use_identity_tracking = False
    auto_update_when_idle = False
    max_concurrent_converts = 1
    _telegram_uploads: list = []

    def get_status(self):
        return {
            "mode": "watchlist",
            "users": self.users,
            "paused": [],
            "recordings": [],
            "automatic_interval_minutes": self.automatic_interval,
            "use_telegram": self.use_telegram,
            "use_identity_tracking": self.use_identity_tracking,
            "auto_update_when_idle": self.auto_update_when_idle,
            "max_concurrent_converts": self.max_concurrent_converts,
            "convert_queue": {"pending": 0, "active": 0, "max_concurrent": 1},
            "media_jobs": list(getattr(self, "media_jobs", [])),
            "telegram_uploads": list(self._telegram_uploads),
            "poll": {},
            "poll_label": None,
            "last_poll_at": None,
            "poll_in_progress": getattr(self, "poll_in_progress", False),
            "activity": list(getattr(self, "activity", [])),
        }

    def active_recording_output_paths(self):
        return set(getattr(self, "_active_paths", ()))

    def _media_jobs_snapshot(self):
        return list(getattr(self, "media_jobs", []))

    def move_leftover_flvs(self):
        from tiktok_live_recorder.utils.utils import (
            default_output_base,
            default_to_fix_dir,
        )
        from tiktok_live_recorder.web.media import move_orphan_flv_files

        return move_orphan_flv_files(
            default_output_base(),
            getattr(self, "output", None),
            self.active_recording_output_paths(),
            default_to_fix_dir(),
        )

    def enqueue_media_repair(self, username, media_path):
        self.repair_requests = getattr(self, "repair_requests", [])
        self.repair_requests.append((username, media_path))
        path = Path(media_path)
        mode = "flv" if path.name.endswith("_flv.mp4") else "repair"
        self.media_jobs = getattr(self, "media_jobs", [])
        self.media_jobs.append(
            {
                "path": media_path,
                "username": username,
                "filename": path.name,
                "mode": mode,
                "status": "queued",
                "queue_position": 1,
            }
        )
        return {"queued": True, "position": 1, "mode": mode}

    def cancel_media_convert(self, username, filename):
        self.cancel_requests = getattr(self, "cancel_requests", [])
        if getattr(self, "cancel_missing", False):
            raise FileNotFoundError("Convert job not found")
        if getattr(self, "cancel_live", False):
            raise ValueError("Cannot cancel a live recording")
        self.cancel_requests.append((username, filename))
        return {
            "cancelled": True,
            "mode": "flv",
            "moved_to": f"/to_fix/{filename}",
            "deleted_output": True,
        }

    def get_ffmpeg_info(self):
        return {
            "path": "/usr/bin/ffmpeg",
            "source": "system",
            "version": "ffmpeg version 7.1.5",
            "hevc_capable": True,
            "hevc_probe": {"legacy": False, "enhanced": False, "roundtrip": True},
        }

    def force_poll(self):
        self.polls = getattr(self, "polls", 0) + 1

    def poll_user_now(self, username):
        self.partial_polls = getattr(self, "partial_polls", [])
        self.partial_polls.append(username)

    def stop_user(self, username):
        return username == "alpha"

    def reload_cookies(self):
        self.cookies_reloaded = True

    def update_runtime_settings(self, **kwargs):
        if kwargs.get("automatic_interval_minutes") is not None:
            self.automatic_interval = kwargs["automatic_interval_minutes"]
        if kwargs.get("use_telegram") is not None:
            self.use_telegram = kwargs["use_telegram"]
        if kwargs.get("use_identity_tracking") is not None:
            self.use_identity_tracking = kwargs["use_identity_tracking"]
        if kwargs.get("auto_update_when_idle") is not None:
            self.auto_update_when_idle = kwargs["auto_update_when_idle"]
        if kwargs.get("max_concurrent_converts") is not None:
            self.max_concurrent_converts = kwargs["max_concurrent_converts"]
        return {
            "automatic_interval_minutes": self.automatic_interval,
            "use_telegram": self.use_telegram,
            "use_identity_tracking": self.use_identity_tracking,
            "auto_update_when_idle": self.auto_update_when_idle,
            "max_concurrent_converts": self.max_concurrent_converts,
        }

    def start_recording_now(self, *, username=None, room_id=None):
        if username == "busy":
            raise RuntimeError("@busy is already recording")
        return {
            "username": username or "roomuser",
            "room_id": room_id or "room-1",
            "status": "started",
        }

    def is_update_pending(self):
        return getattr(self, "_update_pending", False)

    def initiate_restart_update(self):
        if self.is_update_pending():
            raise RuntimeError("Update already in progress")
        self._update_pending = True
        self._idle_update_requested = False

    def queue_update_when_idle(self):
        if self.is_update_pending():
            raise RuntimeError("Update already in progress")
        self._idle_update_requested = True
        return {
            "status": "waiting_idle",
            "message": "Waiting until no recordings or converts are running.",
        }

    def get_update_status(self):
        return {
            "phase": "waiting" if self.is_update_pending() else "idle",
            "message": "",
            "recordings_waiting": 0,
            "converts_waiting": {"pending": 0, "active": 0},
            "error": None,
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
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.scan_media_inventory",
        lambda *_args, **_kwargs: [],
    )
    client = TestClient(create_app(recorder, config))
    return client, recorder, tmp_path


def test_api_status(api_client):
    client, _, _ = api_client
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["users"] == ["alpha"]


def test_dashboard_index_cache_busts_assets(api_client):
    from tiktok_live_recorder.utils.version import get_repo_version

    client, _, _ = api_client
    version = get_repo_version()
    response = client.get("/")
    assert response.status_code == 200
    assert f"/style.css?v={version}" in response.text
    assert f"/js/boot.js?v={version}" in response.text
    assert 'data-version="' in response.text
    assert 'id="settings-modal"' in response.text
    assert 'id="logs-modal"' in response.text
    assert 'id="activity-feed"' in response.text
    assert 'id="activity-filters"' in response.text
    assert response.text.index('id="activity-feed"') < response.text.index(
        'id="summary-strip"'
    )
    assert 'id="summary-filters"' in response.text
    assert 'id="summary-meta"' in response.text
    assert 'id="status-ops"' in response.text
    assert 'id="poll-summary"' not in response.text
    assert 'id="summary-chips"' not in response.text
    assert 'id="connection-banner"' in response.text
    assert 'id="player-actions"' in response.text
    assert 'id="player-delete"' in response.text
    assert 'id="status-filter"' not in response.text
    assert 'id="startup-ffmpeg-data"' in response.text
    assert '"path":"/usr/bin/ffmpeg"' in response.text.replace(" ", "")
    assert "__FFMPEG_JSON__" not in response.text
    assert 'id="update-check-btn"' in response.text
    assert 'id="update-apply-btn"' in response.text


def test_api_events_route_registered(api_client):
    client, _, _ = api_client
    paths = {getattr(route, "path", None) for route in client.app.routes}
    assert "/api/events" in paths


def test_api_version(api_client):
    from tiktok_live_recorder.utils.version import get_repo_version, get_version

    client, _, _ = api_client
    response = client.get("/api/version")
    assert response.status_code == 200
    assert response.json() == {
        "version": get_version(),
        "repo_version": get_repo_version(),
    }


def test_api_update_info(api_client, monkeypatch):
    client, _, _ = api_client
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.is_updatable_install", lambda: True
    )
    response = client.get("/api/update")
    assert response.status_code == 200
    data = response.json()
    assert "running_version" in data
    assert "repo_version" in data
    assert data["updatable"] is True
    assert "release_url" in data


def test_api_update_check(api_client, monkeypatch):
    from tiktok_live_recorder.updater import UpdatePreview

    client, _, _ = api_client
    preview = UpdatePreview(
        current_version="8.20.1",
        latest_version="8.20.2",
        update_available=True,
        scope="hot",
        changed_files=["src/tiktok_live_recorder/web/static/js/update.js"],
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.preview_update_scope", lambda: preview
    )
    response = client.post("/api/update/check")
    assert response.status_code == 200
    data = response.json()
    assert data["update_available"] is True
    assert data["scope"] == "hot"
    assert data["latest"] == "8.20.2"


def test_api_update_apply_hot(api_client, monkeypatch):
    from tiktok_live_recorder.updater import ApplyResult, UpdatePreview

    client, recorder, _ = api_client
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.is_updatable_install", lambda: True
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.preview_update_scope",
        lambda: UpdatePreview(
            current_version="8.20.1",
            latest_version="8.20.2",
            update_available=True,
            scope="hot",
            changed_files=["src/tiktok_live_recorder/web/static/js/update.js"],
        ),
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.apply_hot_update",
        lambda: ApplyResult(
            scope="hot",
            changed_files=["src/tiktok_live_recorder/web/static/js/update.js"],
            static_changed=True,
            synced_dependencies=False,
            message="Dashboard updated.",
        ),
    )
    response = client.post("/api/update/apply")
    assert response.status_code == 200
    assert response.json()["scope"] == "hot"
    assert response.json()["static_changed"] is True
    assert recorder.is_update_pending() is False


def test_api_update_apply_restart(api_client, monkeypatch):
    from tiktok_live_recorder.updater import UpdatePreview

    client, recorder, _ = api_client
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.is_updatable_install", lambda: True
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.preview_update_scope",
        lambda: UpdatePreview(
            current_version="8.20.1",
            latest_version="8.20.2",
            update_available=True,
            scope="restart",
            changed_files=["src/tiktok_live_recorder/web/app.py"],
        ),
    )
    response = client.post("/api/update/apply")
    assert response.status_code == 200
    assert response.json()["scope"] == "restart"
    assert response.json()["status"] == "waiting"
    assert recorder.is_update_pending() is True


def test_api_update_apply_rejects_when_pending(api_client, monkeypatch):
    client, recorder, _ = api_client
    recorder._update_pending = True
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.is_updatable_install", lambda: True
    )
    response = client.post("/api/update/apply")
    assert response.status_code == 409


def test_poll_blocked_during_update(api_client):
    client, recorder, _ = api_client
    recorder._update_pending = True

    def raise_paused():
        raise RuntimeError("Update in progress; polling is paused.")

    recorder.force_poll = raise_paused
    response = client.post("/api/poll")
    assert response.status_code == 409


def test_api_add_remove_user(api_client):
    client, recorder, tmp_path = api_client
    response = client.post("/api/users", json={"username": "beta"})
    assert response.status_code == 200
    assert "beta" in response.json()["users"]
    assert json.loads((tmp_path / "users.json").read_text(encoding="utf-8")) == {
        "users": ["alpha", "beta"]
    }
    assert recorder.partial_polls == ["beta"]
    assert getattr(recorder, "polls", 0) == 0

    response = client.delete("/api/users/beta")
    assert response.status_code == 200
    assert recorder.polls >= 1


def test_api_poll_single_user(api_client):
    client, recorder, _ = api_client
    response = client.post("/api/users/alpha/poll")
    assert response.status_code == 200
    assert response.json() == {"status": "poll_requested", "username": "alpha"}
    assert recorder.partial_polls == ["alpha"]
    assert getattr(recorder, "polls", 0) == 0


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
        json={
            "automatic_interval_minutes": 10,
            "use_telegram": True,
            "use_identity_tracking": False,
            "max_concurrent_converts": 2,
        },
    )
    assert response.status_code == 200
    assert recorder.automatic_interval == 10
    assert recorder.use_telegram is True
    assert recorder.use_identity_tracking is False
    assert recorder.max_concurrent_converts == 2


def test_api_update_apply_rejected_when_not_updatable(api_client, monkeypatch):
    client, _, _ = api_client
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.is_updatable_install", lambda: False
    )
    for path in ("/api/update/apply", "/api/update/when-idle"):
        response = client.post(path)
        assert response.status_code == 422
        assert "immutable" in response.json()["detail"].lower()


def test_api_update_when_idle_queues(api_client, monkeypatch):
    from tiktok_live_recorder.updater import UpdatePreview

    client, recorder, _ = api_client
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.is_updatable_install", lambda: True
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.preview_update_scope",
        lambda: UpdatePreview(
            current_version="8.20.1",
            latest_version="8.20.2",
            update_available=True,
            scope="restart",
            changed_files=["src/tiktok_live_recorder/web/app.py"],
        ),
    )
    response = client.post("/api/update/when-idle")
    assert response.status_code == 200
    assert response.json()["status"] == "waiting_idle"
    assert recorder.is_update_pending() is False
    assert recorder._idle_update_requested is True


def test_api_auto_update_when_idle_runtime(api_client):
    client, recorder, _ = api_client
    response = client.put(
        "/api/settings/runtime",
        json={"auto_update_when_idle": True},
    )
    assert response.status_code == 200
    assert recorder.auto_update_when_idle is True
    payload = client.get("/api/settings/runtime").json()
    assert payload["auto_update_when_idle"] is True


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

    response = client.get("/api/media")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    media = response.json()
    assert "alpha" not in media or not any(
        item["filename"] == "TK_alpha_2026.01.01_12-00-00.mp4"
        for item in media.get("alpha", [])
    )

    response = client.delete("/api/media/alpha/TK_alpha_2026.01.01_13-00-00_flv.mp4")
    assert response.status_code == 400
    assert in_progress.exists()


def test_api_bulk_delete_media(tmp_path):
    keep = tmp_path / "TK_alpha_2026.01.01_10-00-00.mp4"
    keep.write_bytes(b"keep")
    one = tmp_path / "TK_alpha_2026.01.01_12-00-00.mp4"
    one.write_bytes(b"one")
    two = tmp_path / "TK_beta_2026.01.01_12-00-00.mp4"
    two.write_bytes(b"two")
    in_progress = tmp_path / "TK_alpha_2026.01.01_13-00-00_flv.mp4"
    in_progress.write_bytes(b"partial")
    missing_name = "TK_alpha_2026.01.01_14-00-00.mp4"

    recorder = StubRecorder()
    recorder._active_paths = {str(in_progress.resolve())}
    config = RecorderConfig(
        mode=Mode.WATCHLIST,
        users=["alpha", "beta"],
        cookies={},
        output=str(tmp_path),
    )
    client = TestClient(create_app(recorder, config))

    response = client.post(
        "/api/media/delete",
        json={
            "items": [
                {"username": "alpha", "filename": one.name},
                {"username": "beta", "filename": two.name},
                {"username": "alpha", "filename": missing_name},
                {"username": "alpha", "filename": in_progress.name},
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] == 2
    assert payload["failed"] == 2
    assert not one.exists()
    assert not two.exists()
    assert keep.exists()
    assert in_progress.exists()
    by_name = {item["filename"]: item for item in payload["results"]}
    assert by_name[one.name]["ok"] is True
    assert by_name[two.name]["ok"] is True
    assert by_name[missing_name]["ok"] is False
    assert "not found" in by_name[missing_name]["error"].lower()
    assert by_name[in_progress.name]["ok"] is False
    assert "in-progress" in by_name[in_progress.name]["error"].lower()


def test_api_bulk_delete_media_legacy(tmp_path, monkeypatch):
    output_base = tmp_path / "output"
    legacy_dir = output_base / "alpha" / "legacy"
    legacy_dir.mkdir(parents=True)
    legacy = legacy_dir / "2026-07-13_22-50-16_IMG_7691.mp4"
    legacy.write_bytes(b"legacy-video")

    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.default_output_base",
        lambda: output_base,
    )

    recorder = StubRecorder()
    config = RecorderConfig(
        mode=Mode.WATCHLIST,
        users=["alpha"],
        cookies={},
    )
    client = TestClient(create_app(recorder, config))
    response = client.post(
        "/api/media/delete",
        json={
            "items": [
                {
                    "username": "alpha",
                    "filename": legacy.name,
                    "legacy": True,
                }
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] == 1
    assert payload["failed"] == 0
    assert not legacy.exists()


def test_api_bulk_delete_media_validation():
    recorder = StubRecorder()
    config = RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    client = TestClient(create_app(recorder, config))

    response = client.post("/api/media/delete", json={"items": []})
    assert response.status_code == 422

    response = client.post(
        "/api/media/delete",
        json={
            "items": [
                {"username": "alpha", "filename": f"TK_alpha_{i}.mp4"}
                for i in range(201)
            ]
        },
    )
    assert response.status_code == 422


def test_api_leftover_flv_and_move(tmp_path, monkeypatch):
    output_base = tmp_path / "output"
    to_fix = tmp_path / "to_fix"
    user_dir = output_base / "alpha"
    user_dir.mkdir(parents=True)
    orphan = user_dir / "TK_alpha_2026.01.01_14-00-00_flv.mp4"
    orphan.write_bytes(b"orphan")
    active_flv = user_dir / "TK_alpha_2026.01.01_13-00-00_flv.mp4"
    active_flv.write_bytes(b"partial")

    monkeypatch.setattr(
        "tiktok_live_recorder.utils.utils.default_output_base",
        lambda: output_base,
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.default_output_base",
        lambda: output_base,
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.utils.default_to_fix_dir",
        lambda: to_fix,
    )

    recorder = StubRecorder()
    recorder._active_paths = {str(active_flv.resolve())}
    config = RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    client = TestClient(create_app(recorder, config))

    response = client.get("/api/media/leftover-flv")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["files"][0]["filename"] == orphan.name

    response = client.post("/api/media/move-leftover-flv")
    assert response.status_code == 200
    result = response.json()
    assert result["moved"] == 1
    assert result["failed"] == 0
    assert not orphan.exists()
    assert (to_fix / orphan.name).is_file()
    assert active_flv.exists()

    response = client.get("/api/media/leftover-flv")
    assert response.json()["count"] == 0


def test_api_repair_media(tmp_path, monkeypatch):
    output_base = tmp_path / "output"
    user_dir = output_base / "alpha"
    user_dir.mkdir(parents=True)
    broken = user_dir / "TK_alpha_2026.01.01_12-00-00.mp4"
    broken.write_bytes(b"broken")
    flv = user_dir / "TK_alpha_2026.01.01_13-00-00_flv.mp4"
    flv.write_bytes(b"flv")

    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.default_output_base",
        lambda: output_base,
    )

    recorder = StubRecorder()
    config = RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    client = TestClient(create_app(recorder, config))

    response = client.post(
        f"/api/media/alpha/{broken.name}/repair",
    )
    assert response.status_code == 200
    assert response.json() == {"queued": True, "position": 1, "mode": "repair"}
    assert recorder.repair_requests == [("alpha", str(broken.resolve()))]

    response = client.post(f"/api/media/alpha/{flv.name}/repair")
    assert response.status_code == 200
    assert response.json()["mode"] == "flv"

    recorder._active_paths = {str(flv.resolve())}
    response = client.post(f"/api/media/alpha/{flv.name}/repair")
    assert response.status_code == 400

    status = client.get("/api/status").json()
    assert len(status["media_jobs"]) == 2


def test_api_cancel_convert(tmp_path, monkeypatch):
    output_base = tmp_path / "output"
    output_base.mkdir()
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.default_output_base",
        lambda: output_base,
    )
    recorder = StubRecorder()
    config = RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    client = TestClient(create_app(recorder, config))

    filename = "TK_alpha_2026.01.01_12-00-00_flv.mp4"
    response = client.post(f"/api/media/alpha/{filename}/cancel-convert")
    assert response.status_code == 200
    body = response.json()
    assert body["cancelled"] is True
    assert recorder.cancel_requests == [("alpha", filename)]

    recorder.cancel_missing = True
    response = client.post(f"/api/media/alpha/{filename}/cancel-convert")
    assert response.status_code == 404

    recorder.cancel_missing = False
    recorder.cancel_live = True
    response = client.post(f"/api/media/alpha/{filename}/cancel-convert")
    assert response.status_code == 409
