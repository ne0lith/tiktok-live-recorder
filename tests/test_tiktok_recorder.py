import time
from pathlib import Path
from threading import Thread
from unittest.mock import MagicMock

import pytest
from requests import HTTPError

from tiktok_live_recorder.core.tiktok_recorder import (
    TikTokRecorder,
    _is_stream_url_gone,
)
from tiktok_live_recorder.utils.custom_exceptions import (
    LiveNotFound,
    TikTokRecorderError,
    UserLiveError,
)
from tiktok_live_recorder.utils.enums import Mode, TikTokError
from tiktok_live_recorder.utils.recorder_config import RecorderConfig


@pytest.fixture(autouse=True)
def sync_convert_queue(monkeypatch):
    """Run queued conversions inline so recorder tests stay deterministic."""

    from tiktok_live_recorder.core.convert_queue import ConvertQueue
    from tiktok_live_recorder.utils.video_management import VideoManagement

    def immediate_enqueue(self, job):
        with self._lock:
            self._pending += 1
            position = self._pending
        self._semaphore.acquire()
        try:
            with self._lock:
                self._pending = max(0, self._pending - 1)
                self._active += 1
            if job.on_start:
                job.on_start()
            mp4_output = job.output_path.replace("_flv.mp4", ".mp4")
            if job.mode == "repair":
                converted = VideoManagement.repair_mp4_file(
                    job.output_path,
                    job.bitrate,
                    job.ffmpeg_path,
                    on_progress=job.on_progress,
                )
                success = converted
            else:
                converted = VideoManagement.convert_flv_to_mp4(
                    job.output_path,
                    job.bitrate,
                    job.ffmpeg_path,
                    on_progress=job.on_progress,
                )
                success = converted and Path(mp4_output).is_file()
            job.on_complete(
                success, mp4_output if job.mode != "repair" else job.output_path
            )
        except Exception:
            mp4_output = job.output_path.replace("_flv.mp4", ".mp4")
            job.on_complete(False, mp4_output)
        finally:
            with self._lock:
                self._active = max(0, self._active - 1)
            self._semaphore.release()
        return position

    monkeypatch.setattr(ConvertQueue, "enqueue", immediate_enqueue)


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

    def reset_tikrec_warn_flag(self):
        return None

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
    active_recordings = {"alpha": {"thread": active_thread, "room_id": "room-alpha"}}

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
    active_recordings = {"alpha": {"thread": active_thread, "room_id": "room-alpha"}}

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


def test_poll_users_once_handles_network_error_per_user():
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )

    class FailingTikTokAPI:
        def reset_tikrec_warn_flag(self):
            return None

        def get_room_id_from_user(self, user):
            raise __import__("requests").ConnectionError("dns down")

        def is_room_alive(self, room_id, user=None):
            return True

    recorder.tiktok = FailingTikTokAPI()
    active_recordings, _ = recorder._poll_users_once(["alpha"], {}, label="Watchlist")

    assert active_recordings == {}
    assert recorder._last_poll_snapshot["errors"] == ["alpha (network error)"]


def test_poll_users_once_retries_transient_network_error(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    attempts = {"count": 0}

    class FlakyTikTokAPI:
        def reset_tikrec_warn_flag(self):
            return None

        def get_room_id_from_user(self, user):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise __import__("requests").ConnectionError("timeout")
            return "room-alpha"

        def is_room_alive(self, room_id, user=None):
            return True

    recorder.tiktok = FlakyTikTokAPI()
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )
    recorder._spawn_recording_thread = lambda user, room_id: (
        recorder._active_recordings.__setitem__(
            user,
            {
                "thread": MagicMock(is_alive=MagicMock(return_value=True)),
                "room_id": room_id,
            },
        )
    )

    recorder._poll_users_once(["alpha"], {}, label="Watchlist")

    assert attempts["count"] == 2
    assert recorder._last_poll_snapshot["starting"] == []
    assert recorder._last_poll_snapshot["recording"] == ["alpha"]
    assert recorder._last_poll_snapshot["errors"] == []


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
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

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

    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.Thread", ImmediateThread
    )

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
    assert recorder._take_poll_restart_requested() is True


def test_wait_for_next_poll_wakes_early(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder.force_poll()

    start = time.time()
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )
    recorder._wait_for_next_poll(300, label="Watchlist")
    elapsed = time.time() - start

    assert elapsed < 1.0


def test_wait_for_next_poll_priority_check_does_not_end_wait(monkeypatch):
    """Per-user Check during the interval runs, then the wait continues."""
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder.tiktok = PollFakeTikTokAPI()
    checked: list[str] = []
    monkeypatch.setattr(
        recorder,
        "_check_user_live",
        lambda username: checked.append(username) or None,
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    ticks = {"n": 0}
    original_wait = recorder._poll_wake.wait

    def wait_with_check(timeout=None):
        ticks["n"] += 1
        if ticks["n"] == 1:
            recorder.poll_user_now("beta")
            return True
        if ticks["n"] >= 3:
            recorder._stop.set()
            return False
        return original_wait(timeout=0)

    monkeypatch.setattr(recorder._poll_wake, "wait", wait_with_check)
    recorder._wait_for_next_poll(300, label="Watchlist")

    assert checked == ["beta"]
    assert ticks["n"] >= 3


def test_poll_user_now_partial_wake_checks_only_new_user(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder.tiktok = PollFakeTikTokAPI()
    polled: list[list[str]] = []

    monkeypatch.setattr(
        recorder,
        "_poll_users_once",
        lambda users, active, label, force=False: (
            polled.append(list(users)) or active,
            False,
        ),
    )
    stop_after_partial = {"done": False}
    monkeypatch.setattr(recorder, "_should_stop", lambda: stop_after_partial["done"])

    original_partial = recorder._run_partial_poll_cycle

    def partial_then_stop(users, label):
        original_partial(users, label)
        stop_after_partial["done"] = True

    monkeypatch.setattr(recorder, "_run_partial_poll_cycle", partial_then_stop)
    recorder.poll_user_now("beta")
    recorder._wait_for_next_poll(300, label="Watchlist")

    assert polled == [["beta"]]


def test_poll_user_now_during_active_full_poll(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alpha", "beta", "gamma"],
            cookies={},
        )
    )
    recorder.tiktok = PollFakeTikTokAPI()
    checked: list[str] = []

    def check_user(username):
        checked.append(username)
        if username == "alpha":
            recorder.poll_user_now("newuser")
        return None

    monkeypatch.setattr(recorder, "_check_user_live", check_user)
    monkeypatch.setattr(recorder, "_poll_user_order", lambda users: list(users))
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    _, aborted = recorder._poll_users_once(
        ["alpha", "beta", "gamma"],
        {},
        label="Watchlist",
    )

    assert aborted is False
    assert "newuser" in checked
    assert checked.index("newuser") < checked.index("gamma")


def test_spam_poll_user_now_during_full_poll_does_not_abort(monkeypatch):
    """Multiple Checks pause the full poll, run, then resume remaining users."""
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alpha", "beta", "gamma", "delta"],
            cookies={},
        )
    )
    recorder.tiktok = PollFakeTikTokAPI()
    checked: list[str] = []

    def check_user(username):
        checked.append(username)
        if username == "alpha":
            recorder.poll_user_now("prio1")
            recorder.poll_user_now("prio2")
            recorder.poll_user_now("prio3")
        return None

    monkeypatch.setattr(recorder, "_check_user_live", check_user)
    monkeypatch.setattr(recorder, "_poll_user_order", lambda users: list(users))
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    _, aborted = recorder._poll_users_once(
        ["alpha", "beta", "gamma", "delta"],
        {},
        label="Watchlist",
    )

    assert aborted is False
    assert checked == [
        "alpha",
        "prio1",
        "prio2",
        "prio3",
        "beta",
        "gamma",
        "delta",
    ]
    assert not recorder._has_partial_poll_users()
    assert recorder._take_poll_restart_requested() is False


def test_force_poll_still_aborts_after_priority_checks(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alpha", "beta", "gamma"],
            cookies={},
        )
    )
    recorder.tiktok = PollFakeTikTokAPI()
    checked: list[str] = []

    def check_user(username):
        checked.append(username)
        if username == "alpha":
            recorder.poll_user_now("prio")
            recorder.force_poll()
        return None

    monkeypatch.setattr(recorder, "_check_user_live", check_user)
    monkeypatch.setattr(recorder, "_poll_user_order", lambda users: list(users))
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    _, aborted = recorder._poll_users_once(
        ["alpha", "beta", "gamma"],
        {},
        label="Watchlist",
    )

    assert aborted is True
    assert "prio" in checked
    assert "beta" not in checked
    assert "gamma" not in checked


def test_force_poll_during_active_full_poll_aborts_remaining(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alpha", "beta", "gamma"],
            cookies={},
        )
    )
    recorder.tiktok = PollFakeTikTokAPI()
    checked: list[str] = []

    def check_user(username):
        checked.append(username)
        if username == "alpha":
            recorder.force_poll()
        return None

    monkeypatch.setattr(recorder, "_check_user_live", check_user)
    monkeypatch.setattr(recorder, "_poll_user_order", lambda users: list(users))
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    _, aborted = recorder._poll_users_once(
        ["alpha", "beta", "gamma"],
        {},
        label="Watchlist",
    )

    assert aborted is True
    assert checked == ["alpha"]


def test_poll_in_progress_stays_true_during_nested_partial(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha", "gamma"], cookies={})
    )
    recorder.tiktok = PollFakeTikTokAPI()
    poll_flags: list[bool] = []

    original_partial = recorder._run_partial_poll_cycle

    def track_partial(users, label):
        poll_flags.append(recorder._poll_in_progress)
        return original_partial(users, label)

    monkeypatch.setattr(recorder, "_run_partial_poll_cycle", track_partial)

    def check_user(username):
        if username == "alpha":
            recorder.poll_user_now("beta")
        return None

    monkeypatch.setattr(recorder, "_check_user_live", check_user)
    monkeypatch.setattr(recorder, "_poll_user_order", lambda users: list(users))
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    recorder._begin_poll()
    try:
        recorder._poll_users_once(["alpha", "gamma"], {}, label="Watchlist")
    finally:
        recorder._end_poll()

    assert poll_flags == [True]


def test_poll_users_loop_restarts_immediately_on_force_check(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alpha", "beta", "gamma"],
            cookies={},
        )
    )
    recorder.tiktok = PollFakeTikTokAPI()
    cycle_count = {"n": 0}
    checked: list[tuple[int, str]] = []

    def check_user(username):
        checked.append((cycle_count["n"], username))
        if cycle_count["n"] == 1 and username == "alpha":
            recorder.force_poll()
        return None

    monkeypatch.setattr(recorder, "_check_user_live", check_user)
    monkeypatch.setattr(recorder, "_poll_user_order", lambda users: list(users))
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    original_run_cycle = recorder._run_poll_cycle

    def tracked_run_cycle(users, label):
        cycle_count["n"] += 1
        return original_run_cycle(users, label)

    monkeypatch.setattr(recorder, "_run_poll_cycle", tracked_run_cycle)

    completed = 0
    while completed < 2:
        aborted = recorder._run_poll_cycle(["alpha", "beta", "gamma"], "Watchlist")
        completed += 1
        if not aborted:
            break

    assert completed == 2
    assert checked[0] == (1, "alpha")
    assert any(cycle == 2 for cycle, _ in checked)


def test_checked_this_cycle_skips_duplicate_user(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha", "beta"], cookies={})
    )
    recorder.tiktok = PollFakeTikTokAPI()
    recorder._checked_this_cycle = {"beta"}
    checked: list[str] = []

    monkeypatch.setattr(
        recorder,
        "_check_user_live",
        lambda username: checked.append(username) or None,
    )
    monkeypatch.setattr(recorder, "_poll_user_order", lambda users: list(users))
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    recorder._poll_users_once(["alpha", "beta"], {}, label="Watchlist")

    assert checked == ["alpha"]


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
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

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

    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.Thread", ImmediateThread
    )

    active_recordings, _ = recorder._poll_users_once(
        ["alpha"],
        {},
        label="Watchlist",
    )

    assert started == {"user": "alpha", "room_id": "room-alpha"}
    assert active_recordings["alpha"]["room_id"] == "room-alpha"
    assert recorder._last_poll_snapshot["starting"] == []
    assert "alpha" in recorder._last_poll_snapshot["recording"]


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
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    live_thread = MagicMock(spec=Thread)
    live_thread.is_alive.return_value = True
    active_recordings = {"alpha": {"thread": live_thread, "room_id": "shared-room"}}

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


def test_enqueue_media_repair_tracks_job_and_activity(tmp_path, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    broken = tmp_path / "TK_alpha_2026.01.01_12-00-00.mp4"
    broken.write_bytes(b"broken")

    monkeypatch.setattr(
        "tiktok_live_recorder.utils.video_management.VideoManagement.repair_mp4_file",
        lambda *_args, **_kwargs: True,
    )

    result = recorder.enqueue_media_repair("alpha", str(broken))
    assert result["queued"] is True
    assert result["mode"] == "repair"

    status = recorder.get_status()
    assert status["media_jobs"] == []
    messages = [entry["message"] for entry in status["activity"]]
    assert any("Queued manual repair" in message for message in messages)
    assert any("Manual repair started" in message for message in messages)
    assert any("Manual repair succeeded" in message for message in messages)


def test_start_recording_enqueues_conversion(tmp_path, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC, user="alpha", output=str(tmp_path), cookies={}
        )
    )

    class RecordingFakeAPI:
        def __init__(self):
            self.alive_checks = 0

        def get_live_url_candidates(self, room_id, user=None):
            return ["https://cdn.example.com/live.flv"]

        def check_alive(self, room_id, **kwargs):
            self.alive_checks += 1
            return self.alive_checks == 1

        def download_live_stream(self, live_url):
            yield b"x" * 5000

    recorder.tiktok = RecordingFakeAPI()
    convert = MagicMock(return_value=True)
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.video_management.VideoManagement.convert_flv_to_mp4",
        convert,
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    recorder._spawn_recording_thread("alpha", "room-alpha")
    recorder._active_recordings["alpha"]["thread"].join(timeout=5)

    assert "alpha" not in recorder._active_recordings
    convert.assert_called_once()


def test_enqueue_conversion_frees_user_slot_and_tracks_media_job(tmp_path, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST, users=["alpha"], output=str(tmp_path), cookies={}
        )
    )
    raw = tmp_path / "TK_alpha_2026.01.01_12-00-00_flv.mp4"
    raw.write_bytes(b"x" * 100)

    held: list = []

    def hold_enqueue(job):
        held.append(job)
        return 1

    monkeypatch.setattr(recorder._convert_queue, "enqueue", hold_enqueue)
    recorder._active_recordings["alpha"] = {
        "thread": MagicMock(is_alive=MagicMock(return_value=False)),
        "room_id": "room-old",
        "status": "recording",
        "output_path": str(raw),
    }
    recorder._user_stop_events["alpha"] = MagicMock()

    recorder._enqueue_conversion("alpha", str(raw))

    assert "alpha" not in recorder._active_recordings
    assert not recorder._is_user_busy("alpha")
    assert "alpha" not in recorder._user_stop_events
    jobs = recorder._media_jobs_snapshot()
    assert len(jobs) == 1
    assert jobs[0]["username"] == "alpha"
    assert jobs[0]["status"] == "queued"
    assert jobs[0]["queue_position"] == 1
    active_paths = recorder.active_recording_output_paths()
    assert str(raw.resolve()) in active_paths
    assert str(raw.resolve())[: -len("_flv.mp4")] + ".mp4" in active_paths
    assert len(held) == 1


def test_poll_starts_recording_while_convert_media_job_pending(tmp_path, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST, users=["alpha"], output=str(tmp_path), cookies={}
        )
    )
    raw = tmp_path / "TK_alpha_old_flv.mp4"
    raw.write_bytes(b"x")
    media_key = str(raw.resolve())
    recorder._media_jobs[media_key] = {
        "username": "alpha",
        "filename": raw.name,
        "mode": "flv",
        "status": "queued",
        "queued_at": time.time(),
    }
    recorder.tiktok = PollFakeTikTokAPI(live_users={"alpha"})
    started = {}

    def fake_worker(user, room_id):
        started["user"] = user
        started["room_id"] = room_id

    recorder._recording_worker = fake_worker
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    class ImmediateThread:
        def __init__(self, target, args, daemon=False, name=None):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

        def is_alive(self):
            return True

        def join(self, timeout=None):
            return None

    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.Thread", ImmediateThread
    )

    active, _ = recorder._poll_users_once(["alpha"], {}, label="Watchlist")

    assert started == {"user": "alpha", "room_id": "room-alpha"}
    assert active["alpha"]["status"] == "recording"
    assert media_key in recorder._media_jobs


def test_poll_user_now_clears_checked_this_cycle(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    recorder._checked_this_cycle = {"alpha"}
    checked: list[str] = []

    monkeypatch.setattr(
        recorder,
        "_check_user_live",
        lambda username: checked.append(username) or None,
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    recorder.poll_user_now("alpha")
    assert "alpha" not in recorder._checked_this_cycle

    recorder._run_partial_poll_cycle(["alpha"], "Watchlist")
    assert checked == ["alpha"]


def test_poll_user_now_force_checks_paused_user(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    )
    checked: list[str] = []

    monkeypatch.setattr(
        recorder,
        "_check_user_live",
        lambda username: checked.append(username) or None,
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.utils.read_paused_users",
        lambda: {"alpha"},
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    recorder._poll_users_once(["alpha"], {}, label="Watchlist")
    assert checked == []

    recorder._poll_users_once(["alpha"], {}, label="Watchlist", force=True)
    assert checked == ["alpha"]


def test_start_recording_finalizes_when_user_goes_offline(tmp_path, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC, user="alpha", output=str(tmp_path), cookies={}
        )
    )

    class RecordingFakeAPI:
        def __init__(self):
            self.alive_checks = 0

        def get_live_url_candidates(self, room_id, user=None):
            return ["https://cdn.example.com/live.flv"]

        def check_alive(self, room_id, **kwargs):
            self.alive_checks += 1
            # Live for the initial open; offline once the CDN stream ends.
            return self.alive_checks == 1

        def download_live_stream(self, live_url):
            yield b"x" * 5000

    fake = RecordingFakeAPI()
    recorder.tiktok = fake
    convert = MagicMock()
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.video_management.VideoManagement.convert_flv_to_mp4",
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
        RecorderConfig(
            mode=Mode.AUTOMATIC, user="alpha", output=str(tmp_path), cookies={}
        )
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

        def check_alive(self, room_id, **kwargs):
            return True

        def download_live_stream(self, live_url):
            self.tried.append(live_url)
            err = HTTPError("404 Client Error: Not Found")
            err.response = MagicMock(status_code=404)
            raise err

    fake = FakeAPI()
    recorder.tiktok = fake
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.video_management.VideoManagement.convert_flv_to_mp4",
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

        def check_alive(self, room_id, **kwargs):
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
        "tiktok_live_recorder.utils.video_management.VideoManagement.convert_flv_to_mp4",
        convert,
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

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

    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.Thread", ImmediateThread
    )

    recorder._poll_wake.clear()
    recorder._poll_users_once(["alpha"], {}, label="Watchlist")
    recorder._poll_users_once(["alpha"], {}, label="Watchlist")
    assert convert.call_count == 1
    assert fake.download_calls == 2
    assert len(list(tmp_path.glob("TK_alpha_*_flv.mp4"))) >= 1


def test_poll_user_order_shuffles_multi_user_list(monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST, users=["alpha", "beta", "gamma"], cookies={}
        )
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.random.shuffle",
        lambda items: items.reverse(),
    )

    assert recorder._poll_user_order(["alpha", "beta", "gamma"]) == [
        "gamma",
        "beta",
        "alpha",
    ]
    assert recorder._poll_user_order(["solo"]) == ["solo"]


def test_poll_users_once_spaces_checks_and_logs_plan(monkeypatch, caplog):
    import logging

    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST, users=["alpha", "beta", "gamma"], cookies={}
        )
    )
    recorder.tiktok = PollFakeTikTokAPI()
    sleeps: list[float] = []
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.random.shuffle",
        lambda items: items.reverse(),
    )

    with caplog.at_level(logging.DEBUG):
        recorder._poll_users_once(
            ["alpha", "beta", "gamma"],
            {},
            label="Watchlist",
        )

    assert recorder.tiktok.calls == [
        "get_room_id_from_user:gamma",
        "is_room_alive:room-gamma",
        "get_room_id_from_user:beta",
        "is_room_alive:room-beta",
        "get_room_id_from_user:alpha",
        "is_room_alive:room-alpha",
    ]
    from tiktok_live_recorder.core.tiktok_recorder import POLL_USER_DELAY_SECONDS

    assert sleeps == [POLL_USER_DELAY_SECONDS, POLL_USER_DELAY_SECONDS]
    assert "Watchlist poll: checking 3 users in shuffled order" in caplog.text
    assert "Watchlist poll order: @gamma, @beta, @alpha" in caplog.text


def test_request_stop_ends_recording_and_finalizes(tmp_path, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.AUTOMATIC, user="alpha", output=str(tmp_path), cookies={}
        )
    )

    class FakeAPI:
        def get_live_url_candidates(self, room_id, user=None):
            return ["https://cdn.example.com/live.flv"]

        def check_alive(self, room_id, **kwargs):
            return True

        def download_live_stream(self, live_url):
            yield b"x" * 5000
            recorder.request_stop()
            yield b"y" * 1000

    recorder.tiktok = FakeAPI()
    convert = MagicMock()
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.video_management.VideoManagement.convert_flv_to_mp4",
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
        RecorderConfig(
            mode=Mode.AUTOMATIC, user="alpha", output=str(tmp_path), cookies={}
        )
    )

    class FakeAPI:
        def __init__(self):
            self.refresh_calls = 0

        def get_live_url_candidates(self, room_id, user=None):
            self.refresh_calls += 1
            if self.refresh_calls == 1:
                return ["https://cdn.example.com/live.flv"]
            raise UserLiveError(TikTokError.USER_NOT_CURRENTLY_LIVE)

        def check_alive(self, room_id, **kwargs):
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
        "tiktok_live_recorder.utils.video_management.VideoManagement.convert_flv_to_mp4",
        convert,
    )

    recorder.start_recording("alpha", "room-alpha")

    assert fake.refresh_calls >= 2
    convert.assert_called_once()
    files = list(tmp_path.glob("TK_alpha_*_flv.mp4"))
    assert len(files) == 1
    assert files[0].stat().st_size >= 8000
