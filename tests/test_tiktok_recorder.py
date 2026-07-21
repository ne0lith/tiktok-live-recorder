import sys
import time
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_recorder import TikTokRecorder, _is_stream_url_gone  # noqa: E402
from utils.custom_exceptions import (  # noqa: E402
    LiveNotFound,
    TikTokRecorderError,
    UserLiveError,
)
from utils.enums import Mode, TikTokError  # noqa: E402
from utils.recorder_config import RecorderConfig  # noqa: E402
from requests import HTTPError  # noqa: E402


def test_is_stream_url_gone_detects_404():
    response = MagicMock()
    response.status_code = 404
    err = HTTPError("404 Client Error", response=response)
    assert _is_stream_url_gone(err) is True
    assert _is_stream_url_gone(HTTPError("connection reset")) is False



class FakeTikTokAPI:
    def __init__(self, blacklisted=True):
        self.blacklisted = blacklisted
        self.calls = []

    def is_country_blacklisted(self):
        self.calls.append("is_country_blacklisted")
        return self.blacklisted

    def get_room_id_from_user(self, user):
        self.calls.append(f"get_room_id_from_user:{user}")
        return "1234567890"

    def get_user_from_room_id(self, room_id):
        self.calls.append(f"get_user_from_room_id:{room_id}")
        return "creator"

    def get_sec_uid(self):
        self.calls.append("get_sec_uid")
        return "sec_uid"

    def is_room_alive(self, room_id, user=None):
        self.calls.append(f"is_room_alive:{room_id}")
        return True


def test_setup_resolves_room_id_before_country_check_for_manual_user():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.MANUAL, user="creator", cookies={})
    )
    fake_api = FakeTikTokAPI(blacklisted=True)
    recorder.tiktok = fake_api

    recorder._setup()

    assert recorder.room_id == "1234567890"
    assert fake_api.calls == [
        "get_room_id_from_user:creator",
        "is_country_blacklisted",
        "is_room_alive:1234567890",
    ]


def test_setup_keeps_followers_country_check_before_sec_uid():
    recorder = TikTokRecorder(RecorderConfig(mode=Mode.FOLLOWERS, cookies={}))
    fake_api = FakeTikTokAPI(blacklisted=True)
    recorder.tiktok = fake_api

    with pytest.raises(TikTokRecorderError, match="Captcha required"):
        recorder._setup()

    assert fake_api.calls == ["is_country_blacklisted"]


def test_setup_keeps_automatic_mode_blocked_after_room_resolution():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.AUTOMATIC, user="creator", cookies={})
    )
    fake_api = FakeTikTokAPI(blacklisted=True)
    recorder.tiktok = fake_api

    with pytest.raises(TikTokRecorderError, match="Automatic mode is available"):
        recorder._setup()

    assert recorder.room_id == "1234567890"
    assert fake_api.calls == [
        "get_room_id_from_user:creator",
        "is_country_blacklisted",
    ]


def test_setup_keeps_manual_room_id_allowed_when_country_check_is_blocked():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.MANUAL, room_id="1234567890", cookies={})
    )
    fake_api = FakeTikTokAPI(blacklisted=True)
    recorder.tiktok = fake_api

    recorder._setup()

    assert recorder.room_id == "1234567890"
    assert fake_api.calls == [
        "get_user_from_room_id:1234567890",
        "is_country_blacklisted",
        "is_room_alive:1234567890",
    ]


class PollFakeTikTokAPI:
    def __init__(self, live_users=None):
        self.live_users = set(live_users or [])
        self.calls = []

    def get_room_id_from_user(self, user):
        self.calls.append(f"get_room_id_from_user:{user}")
        return f"room-{user}"

    def is_room_alive(self, room_id, user=None):
        self.calls.append(f"is_room_alive:{room_id}")
        user = user or room_id.removeprefix("room-")
        return user in self.live_users


def test_setup_watchlist_skips_single_user_resolution():
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alpha", "beta"],
            cookies={},
        )
    )
    fake_api = PollFakeTikTokAPI()
    fake_api.is_country_blacklisted = MagicMock(return_value=False)
    recorder.tiktok = fake_api

    recorder._setup()

    assert recorder.users == ["alpha", "beta"]
    assert fake_api.calls == []


def test_reload_watchlist_users_reads_file_and_logs_changes(tmp_path):
    users_file = tmp_path / "users.json"
    users_file.write_text('{"users": ["alpha", "beta"]}', encoding="utf-8")
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alpha"],
            users_file=str(users_file),
            cookies={},
        )
    )

    loaded = recorder._reload_watchlist_users()

    assert loaded == ["alpha", "beta"]
    assert recorder.users == ["alpha", "beta"]

    users_file.write_text('{"users": ["alpha", "gamma"]}', encoding="utf-8")
    loaded = recorder._reload_watchlist_users()

    assert loaded == ["alpha", "gamma"]


def test_reload_watchlist_users_without_file_returns_static_list():
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alpha", "beta"],
            cookies={},
        )
    )

    assert recorder._reload_watchlist_users() == ["alpha", "beta"]


def test_poll_users_once_keeps_recording_user_removed_from_watchlist():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["beta"], cookies={})
    )
    recorder.tiktok = PollFakeTikTokAPI(live_users=set())
    recorder._recording_worker = MagicMock()

    active_thread = MagicMock(spec=Thread)
    active_thread.is_alive.return_value = True
    active_recordings = {
        "alpha": {"thread": active_thread, "room_id": "room-alpha"}
    }

    recorder._poll_users_once(
        ["beta"],
        active_recordings,
        label="Watchlist",
    )

    assert "alpha" in active_recordings
    assert recorder.tiktok.calls == [
        "get_room_id_from_user:beta",
        "is_room_alive:room-beta",
    ]


def test_poll_users_once_logs_offline_and_skips_active_recording(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha", "beta"], cookies={})
    )
    recorder.tiktok = PollFakeTikTokAPI(live_users=set())
    recorder._recording_worker = MagicMock()

    active_thread = MagicMock(spec=Thread)
    active_thread.is_alive.return_value = True
    active_recordings = {
        "alpha": {"thread": active_thread, "room_id": "room-alpha"}
    }

    recorder._poll_users_once(
        ["alpha", "beta"],
        active_recordings,
        label="Watchlist",
    )

    assert recorder.tiktok.calls == [
        "get_room_id_from_user:beta",
        "is_room_alive:room-beta",
    ]
    recorder._recording_worker.assert_not_called()


def test_recording_worker_catches_user_live_error():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder.start_recording = MagicMock(
        side_effect=UserLiveError("Live access blocked")
    )

    recorder._recording_worker("alpha", "room-alpha")

    assert recorder._recording_results["alpha"] == "error"


def test_poll_users_once_cleans_failed_thread_as_error():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder.tiktok = PollFakeTikTokAPI()

    dead_thread = MagicMock(spec=Thread)
    dead_thread.is_alive.return_value = False
    recorder._recording_results["alpha"] = "error"

    recorder._poll_users_once(
        ["alpha"],
        {"alpha": {"thread": dead_thread, "room_id": "room-alpha"}},
        label="Watchlist",
    )

    assert "alpha" not in recorder._recording_results


def test_poll_users_once_rechecks_finished_user_same_cycle(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder.tiktok = PollFakeTikTokAPI(live_users={"alpha"})
    started = {}

    def fake_worker(user, room_id):
        started["user"] = user
        started["room_id"] = room_id

    recorder._recording_worker = fake_worker
    monkeypatch.setattr("core.tiktok_recorder.time.sleep", lambda *_: None)

    class ImmediateThread:
        def __init__(self, target, args, daemon=False, name=None):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

        def is_alive(self):
            return False

        def join(self, timeout=None):
            return None

    monkeypatch.setattr("core.tiktok_recorder.Thread", ImmediateThread)

    dead_thread = MagicMock(spec=Thread)
    dead_thread.is_alive.return_value = False

    recorder._poll_users_once(
        ["alpha"],
        {"alpha": {"thread": dead_thread, "room_id": "room-alpha"}},
        label="Watchlist",
    )

    assert started == {"user": "alpha", "room_id": "room-alpha"}


def test_recording_worker_wakes_poll_loop():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder.start_recording = MagicMock()

    recorder._recording_worker("alpha", "room-alpha")

    assert recorder._poll_wake.is_set()


def test_wait_for_next_poll_wakes_early(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder._poll_wake.set()

    start = time.time()
    monkeypatch.setattr("core.tiktok_recorder.time.sleep", lambda *_: None)
    recorder._wait_for_next_poll(300)
    elapsed = time.time() - start

    assert elapsed < 1.0


def test_poll_users_once_starts_recording_for_live_user(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder.tiktok = PollFakeTikTokAPI(live_users={"alpha"})
    started = {}

    def fake_worker(user, room_id):
        started["user"] = user
        started["room_id"] = room_id

    recorder._recording_worker = fake_worker
    monkeypatch.setattr("core.tiktok_recorder.time.sleep", lambda *_: None)

    class ImmediateThread:
        def __init__(self, target, args, daemon=False, name=None):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

        def is_alive(self):
            return False

        def join(self, timeout=None):
            return None

    monkeypatch.setattr("core.tiktok_recorder.Thread", ImmediateThread)

    active_recordings = recorder._poll_users_once(
        ["alpha"],
        {},
        label="Watchlist",
    )

    assert started == {"user": "alpha", "room_id": "room-alpha"}
    assert active_recordings["alpha"]["room_id"] == "room-alpha"


def test_poll_users_once_skips_duplicate_room(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alpha", "beta"],
            cookies={},
        )
    )
    recorder.tiktok = PollFakeTikTokAPI(live_users={"alpha", "beta"})
    recorder._recording_worker = MagicMock()
    monkeypatch.setattr("core.tiktok_recorder.time.sleep", lambda *_: None)

    live_thread = MagicMock(spec=Thread)
    live_thread.is_alive.return_value = True
    active_recordings = {
        "alpha": {"thread": live_thread, "room_id": "shared-room"}
    }

    class FakeAPI(PollFakeTikTokAPI):
        def get_room_id_from_user(self, user):
            return "shared-room"

    recorder.tiktok = FakeAPI(live_users={"alpha", "beta"})

    recorder._poll_users_once(
        ["alpha", "beta"],
        active_recordings,
        label="Watchlist",
    )

    recorder._recording_worker.assert_not_called()


def test_start_recording_finalizes_when_user_goes_offline(tmp_path, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.AUTOMATIC, user="alpha", output=str(tmp_path), cookies={})
    )

    class RecordingFakeAPI:
        def __init__(self):
            self.alive_checks = 0

        def get_live_url_candidates(self, room_id, user=None):
            return ["https://cdn.example.com/live.flv"]

        def check_alive(self, room_id):
            self.alive_checks += 1
            # Live for the initial open; offline once the CDN stream ends.
            return self.alive_checks == 1

        def download_live_stream(self, live_url):
            yield b"x" * 5000

    fake = RecordingFakeAPI()
    recorder.tiktok = fake
    convert = MagicMock()
    monkeypatch.setattr(
        "core.tiktok_recorder.VideoManagement.convert_flv_to_mp4",
        convert,
    )

    recorder.start_recording("alpha", "room-alpha")

    files = list(tmp_path.glob("TK_alpha_*_flv.mp4"))
    assert len(files) == 1
    assert files[0].stat().st_size >= 5000
    assert fake.alive_checks >= 2
    convert.assert_called_once()


def test_cdn_404_tries_all_refreshed_candidates_before_giving_up(tmp_path, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.AUTOMATIC, user="alpha", output=str(tmp_path), cookies={})
    )
    urls = [
        "https://cdn.example.com/a.flv",
        "https://cdn.example.com/b.flv",
        "https://cdn.example.com/c.flv",
    ]

    class FakeAPI:
        def __init__(self):
            self.tried = []

        def get_live_url_candidates(self, room_id, user=None):
            return list(urls)

        def check_alive(self, room_id):
            return True

        def download_live_stream(self, live_url):
            self.tried.append(live_url)
            err = HTTPError("404 Client Error: Not Found")
            err.response = MagicMock(status_code=404)
            raise err

    fake = FakeAPI()
    recorder.tiktok = fake
    monkeypatch.setattr(
        "core.tiktok_recorder.VideoManagement.convert_flv_to_mp4",
        MagicMock(),
    )

    with pytest.raises(LiveNotFound):
        recorder.start_recording("alpha", "room-alpha")

    assert fake.tried == urls


def test_404_after_data_finalizes_then_poll_can_start_again(tmp_path, monkeypatch):
    """Simulate: record → CDN 404 while offline → finalize → later live starts clean."""
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC,
            users=["alpha"],
            output=str(tmp_path),
            cookies={},
        )
    )

    class FakeAPI:
        def __init__(self):
            self.live = True
            self.download_calls = 0

        def get_room_id_from_user(self, user):
            return "room-alpha"

        def is_room_alive(self, room_id, user=None):
            return self.live

        def check_alive(self, room_id):
            return self.live

        def get_live_url_candidates(self, room_id, user=None):
            return ["https://cdn.example.com/live.flv"]

        def download_live_stream(self, live_url):
            self.download_calls += 1
            if self.download_calls == 1:
                yield b"x" * 8000
                self.live = False
                err = HTTPError("404 Client Error: Not Found")
                err.response = MagicMock(status_code=404)
                raise err
            yield b"y" * 8000
            self.live = False

    fake = FakeAPI()
    recorder.tiktok = fake
    convert = MagicMock()
    monkeypatch.setattr(
        "core.tiktok_recorder.VideoManagement.convert_flv_to_mp4",
        convert,
    )
    monkeypatch.setattr("core.tiktok_recorder.time.sleep", lambda *_: None)

    # First session: download some bytes, then 404 + offline → finalize
    recorder.start_recording("alpha", "room-alpha")
    convert.assert_called_once()
    first_files = list(tmp_path.glob("TK_alpha_*_flv.mp4"))
    assert first_files

    # Watchlist slot is free; user goes live again → new recording can start
    fake.live = True
    convert.reset_mock()
    recorder._stop.clear()

    class ImmediateThread:
        def __init__(self, target, args, daemon=False, name=None):
            self._target = target
            self._args = args
            self._alive = False

        def start(self):
            self._alive = True
            self._target(*self._args)
            self._alive = False

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            return None

    monkeypatch.setattr("core.tiktok_recorder.Thread", ImmediateThread)

    recorder._poll_users_once(["alpha"], {}, label="Watchlist")
    assert convert.call_count == 1
    assert fake.download_calls == 2
    assert len(list(tmp_path.glob("TK_alpha_*_flv.mp4"))) >= 1

def test_request_stop_ends_recording_and_finalizes(tmp_path, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.AUTOMATIC, user="alpha", output=str(tmp_path), cookies={})
    )

    class FakeAPI:
        def get_live_url_candidates(self, room_id, user=None):
            return ["https://cdn.example.com/live.flv"]

        def check_alive(self, room_id):
            return True

        def download_live_stream(self, live_url):
            yield b"x" * 5000
            recorder.request_stop()
            yield b"y" * 1000

    recorder.tiktok = FakeAPI()
    convert = MagicMock()
    monkeypatch.setattr(
        "core.tiktok_recorder.VideoManagement.convert_flv_to_mp4",
        convert,
    )

    recorder.start_recording("alpha", "room-alpha")
    convert.assert_called_once()
    assert recorder._should_stop()


def test_cdn_refresh_offline_still_finalizes(tmp_path, monkeypatch):
    """
    After data is written, CDN 404 + URL refresh raising UserLiveError must
    still convert — that exception used to escape the except-handler and skip finalize.
    """
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.AUTOMATIC, user="alpha", output=str(tmp_path), cookies={})
    )

    class FakeAPI:
        def __init__(self):
            self.refresh_calls = 0

        def get_live_url_candidates(self, room_id, user=None):
            self.refresh_calls += 1
            if self.refresh_calls == 1:
                return ["https://cdn.example.com/live.flv"]
            raise UserLiveError(TikTokError.USER_NOT_CURRENTLY_LIVE)

        def check_alive(self, room_id):
            # Stale alive: CDN already 404'd but check_alive still true briefly.
            return True

        def download_live_stream(self, live_url):
            yield b"x" * 8000
            err = HTTPError("404 Client Error: Not Found")
            err.response = MagicMock(status_code=404)
            raise err

    fake = FakeAPI()
    recorder.tiktok = fake
    convert = MagicMock()
    monkeypatch.setattr(
        "core.tiktok_recorder.VideoManagement.convert_flv_to_mp4",
        convert,
    )

    recorder.start_recording("alpha", "room-alpha")

    assert fake.refresh_calls >= 2
    convert.assert_called_once()
    files = list(tmp_path.glob("TK_alpha_*_flv.mp4"))
    assert len(files) == 1
    assert files[0].stat().st_size >= 8000
