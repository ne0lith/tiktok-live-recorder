import random
import signal
import time
from collections import deque
from http.client import HTTPException
from pathlib import Path
from threading import Event, Lock, Thread

from requests import HTTPError, RequestException

from tiktok_live_recorder.core.convert_queue import ConvertJob, ConvertQueue
from tiktok_live_recorder.core.tiktok_api import TikTokAPI
from tiktok_live_recorder.utils.logger_manager import logger
from tiktok_live_recorder.utils.recorder_config import RecorderConfig
from tiktok_live_recorder.utils.ffmpeg_setup import (
    describe_ffmpeg_binary,
    get_startup_ffmpeg_info,
    normalize_cdn_url,
)
from tiktok_live_recorder.utils.utils import output_dir_for_user
from tiktok_live_recorder.utils.custom_exceptions import (
    LiveNotFound,
    UserLiveError,
    TikTokRecorderError,
)
from tiktok_live_recorder.utils.enums import Mode, Error, TimeOut, TikTokError

# Pause between watchlist/followers poll steps to avoid bursting TikTok/tikrec APIs.
POLL_USER_DELAY_SECONDS = 0.5

_POST_RECORD_STATUSES = frozenset({"convert_queued", "converting"})
_BUSY_STATUSES = frozenset({"recording", "stopping", "convert_queued", "converting"})


def _is_stream_url_gone(exc: BaseException) -> bool:
    """CDN 404/403/410 means this pull URL is dead (live usually over or rotated)."""
    if isinstance(exc, HTTPError) and exc.response is not None:
        return exc.response.status_code in (401, 403, 404, 410)
    text = str(exc)
    return any(
        code in text
        for code in (" 401 ", " 403 ", " 404 ", " 410 ", "404 Client", "403 Client")
    )


class TikTokRecorder:
    def __init__(self, config: RecorderConfig):
        self.tiktok = TikTokAPI(proxy=config.proxy, cookies=config.cookies)

        self.url = config.url
        self.user = config.user
        self.users = config.users
        self.users_file = config.users_file
        self.room_id = config.room_id
        self.mode = config.mode
        self.automatic_interval = config.automatic_interval
        self.max_concurrent_converts = config.max_concurrent_converts
        self.duration = config.duration
        self.output = config.output
        self.bitrate = config.bitrate
        self.ffmpeg_path = config.ffmpeg_path
        self._ffmpeg_info = get_startup_ffmpeg_info() or describe_ffmpeg_binary(
            self.ffmpeg_path
        )
        self._stopped_by_signal: int | None = None
        self.use_telegram = config.use_telegram
        self._proxy = config.proxy
        self._cookies = config.cookies
        self._recording_results: dict[str, str] = {}
        self._stop = Event()
        self._poll_wake = Event()
        self._active_recordings: dict = {}
        self._user_stop_events: dict[str, Event] = {}
        self._state_lock = Lock()
        self._last_poll_at: float | None = None
        self._last_poll_snapshot: dict | None = None
        self._poll_label: str | None = None
        self._telegram_uploads: list[dict] = []
        self._max_telegram_upload_history = 20
        self._poll_in_progress_depth = 0
        self._poll_in_progress = False
        self._checked_this_cycle: set[str] = set()
        self._activity: deque[dict] = deque(maxlen=50)
        self._poll_wake_reason: str | None = None
        self._partial_poll_users: list[str] = []
        self._convert_queue = ConvertQueue(max_concurrent=self.max_concurrent_converts)

    @staticmethod
    def _entry_still_active(entry: dict) -> bool:
        status = entry.get("status", "recording")
        if status in _POST_RECORD_STATUSES:
            return True
        thread = entry.get("thread")
        return bool(thread and thread.is_alive())

    def request_stop(self):
        """Signal all loops/threads to finish and finalize open recordings."""
        self._stop.set()
        self._poll_wake.set()

    def _wake_poll_loop(self, *, reason: str | None = None):
        """Interrupt the poll sleep so the watchlist can be checked."""
        if reason is not None:
            self._set_poll_wake_reason(reason)
        self._poll_wake.set()

    def _set_poll_wake_reason(self, reason: str) -> None:
        with self._state_lock:
            self._poll_wake_reason = reason

    def _take_poll_wake_reason(self) -> str:
        with self._state_lock:
            reason = self._poll_wake_reason or "full"
            self._poll_wake_reason = None
            return reason

    def _queue_partial_poll_users(self, usernames: list[str]) -> None:
        with self._state_lock:
            for name in usernames:
                normalized = name.lstrip("@").strip()
                if not normalized:
                    continue
                if normalized not in self._partial_poll_users:
                    self._partial_poll_users.append(normalized)

    def _take_partial_poll_users(self) -> list[str]:
        with self._state_lock:
            users = list(self._partial_poll_users)
            self._partial_poll_users.clear()
            return users

    def _drain_poll_requests(self, label: str) -> bool:
        """Handle pending poll wake requests. Returns True if the current cycle should abort."""
        if not self._poll_wake.is_set():
            return False
        self._poll_wake.clear()
        reason = self._take_poll_wake_reason()
        if reason == "partial":
            partial_users = self._take_partial_poll_users()
            if partial_users:
                if self._run_partial_poll_cycle(partial_users, label):
                    return True
            return False
        self._take_partial_poll_users()
        return True

    def _wait_for_next_poll(self, seconds: float, *, label: str):
        """Sleep until the poll interval elapses, handling priority single-user polls."""
        deadline = time.time() + seconds
        while not self._should_stop():
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            if self._poll_wake.wait(timeout=min(remaining, 1.0)):
                if self._drain_poll_requests(label):
                    logger.info("Recording ended — rechecking watchlist early")
                    return

    def _should_stop(self) -> bool:
        return self._stop.is_set()

    def _should_stop_user(self, user: str) -> bool:
        if self._should_stop():
            return True
        stop_event = self._user_stop_events.get(user)
        return bool(stop_event and stop_event.is_set())

    def force_poll(self) -> None:
        """Interrupt the poll sleep so the full watchlist is checked immediately."""
        self.record_activity("poll", "Manual poll requested")
        self._wake_poll_loop(reason="full")

    def poll_user_now(self, username: str) -> None:
        """Check one user now without resetting the full watchlist poll schedule."""
        username = username.lstrip("@").strip()
        if not username:
            return
        self._queue_partial_poll_users([username])
        self.record_activity(
            "poll",
            f"Priority check for @{username}",
            username=username,
        )
        self._wake_poll_loop(reason="partial")

    def record_activity(
        self,
        kind: str,
        message: str,
        *,
        username: str | None = None,
    ) -> None:
        with self._state_lock:
            self._activity.appendleft(
                {
                    "at": time.time(),
                    "kind": kind,
                    "message": message,
                    "username": username,
                }
            )

    def _begin_poll(self) -> None:
        with self._state_lock:
            self._poll_in_progress_depth += 1
            self._poll_in_progress = self._poll_in_progress_depth > 0

    def _end_poll(self) -> None:
        with self._state_lock:
            self._poll_in_progress_depth = max(0, self._poll_in_progress_depth - 1)
            self._poll_in_progress = self._poll_in_progress_depth > 0

    def stop_user(self, username: str) -> bool:
        """Request graceful stop for one active recording."""
        username = username.lstrip("@").strip()
        entry = self._active_recordings.get(username)
        if not entry:
            return False
        thread = entry.get("thread")
        if thread is None or not thread.is_alive():
            return False
        stop_event = self._user_stop_events.setdefault(username, Event())
        stop_event.set()
        with self._state_lock:
            entry["status"] = "stopping"
        self.record_activity("recording", "Stop requested", username=username)
        return True

    def reload_cookies(self) -> None:
        """Reload cookies from disk into the active TikTok API client."""
        from tiktok_live_recorder.utils.utils import read_cookies

        self._cookies = read_cookies()
        self.tiktok = TikTokAPI(proxy=self._proxy, cookies=self._cookies)

    def get_status(self) -> dict:
        from tiktok_live_recorder.utils.utils import read_paused_users

        paused = sorted(read_paused_users())
        users = list(self.users or [])
        now = time.time()

        with self._state_lock:
            active_entries = {
                username: dict(entry)
                for username, entry in self._active_recordings.items()
            }
            snapshot = dict(self._last_poll_snapshot or {})
            telegram_uploads = list(self._telegram_uploads)
            poll_in_progress = self._poll_in_progress
            activity = list(self._activity)

        recordings = []
        for username, entry in active_entries.items():
            if not self._entry_still_active(entry):
                continue
            thread = entry.get("thread")
            started_at = entry.get("started_at")
            elapsed = (now - started_at) if started_at else None
            output_path = entry.get("output_path")
            file_size = entry.get("bytes_written", 0)
            if output_path:
                try:
                    file_size = max(file_size, Path(output_path).stat().st_size)
                except OSError:
                    pass
            status = entry.get("status", "recording")
            recordings.append(
                {
                    "username": username,
                    "room_id": entry.get("room_id"),
                    "status": status,
                    "started_at": started_at,
                    "elapsed_seconds": round(elapsed, 1)
                    if elapsed is not None
                    else None,
                    "bytes_written": file_size,
                    "output_path": output_path,
                    "is_alive": status in _POST_RECORD_STATUSES
                    or bool(thread and thread.is_alive()),
                    "convert_progress": entry.get("convert_progress"),
                }
            )

        convert_queue = self._convert_queue.stats()

        return {
            "mode": self.mode.name.lower(),
            "users": users,
            "paused": paused,
            "users_file": self.users_file,
            "automatic_interval_minutes": self.automatic_interval,
            "use_telegram": self.use_telegram,
            "max_concurrent_converts": self.max_concurrent_converts,
            "convert_queue": convert_queue,
            "last_poll_at": self._last_poll_at,
            "poll_label": self._poll_label,
            "poll": snapshot,
            "recordings": recordings,
            "telegram_uploads": telegram_uploads,
            "poll_in_progress": poll_in_progress,
            "activity": activity,
            "ffmpeg": self.get_ffmpeg_info(),
        }

    def get_ffmpeg_info(self) -> dict:
        """Return resolved FFmpeg metadata for the dashboard."""
        cached = get_startup_ffmpeg_info()
        if cached and cached.get("path"):
            return cached
        if self.ffmpeg_path:
            self._ffmpeg_info = describe_ffmpeg_binary(self.ffmpeg_path)
        return self._ffmpeg_info

    def update_runtime_settings(
        self,
        *,
        automatic_interval_minutes: int | None = None,
        use_telegram: bool | None = None,
        max_concurrent_converts: int | None = None,
    ) -> dict:
        from tiktok_live_recorder.utils.utils import write_runtime_settings

        if automatic_interval_minutes is not None:
            if automatic_interval_minutes < 1:
                raise ValueError("automatic_interval_minutes must be at least 1")
            self.automatic_interval = automatic_interval_minutes
        if use_telegram is not None:
            self.use_telegram = use_telegram
        if max_concurrent_converts is not None:
            if max_concurrent_converts < 1:
                raise ValueError("max_concurrent_converts must be at least 1")
            self.max_concurrent_converts = max_concurrent_converts
            self._convert_queue.set_max_concurrent(max_concurrent_converts)
        settings = {
            "automatic_interval_minutes": self.automatic_interval,
            "use_telegram": self.use_telegram,
            "max_concurrent_converts": self.max_concurrent_converts,
        }
        write_runtime_settings(settings)
        return settings

    def _record_telegram_upload(
        self,
        username: str,
        filename: str,
        status: str,
        message: str,
    ) -> None:
        with self._state_lock:
            self._telegram_uploads.insert(
                0,
                {
                    "username": username,
                    "file": filename,
                    "status": status,
                    "message": message,
                    "at": time.time(),
                },
            )
            del self._telegram_uploads[self._max_telegram_upload_history :]
        self.record_activity(
            "telegram",
            f"{filename}: {message}",
            username=username,
        )

    def _maybe_upload_to_telegram(self, user: str, file_path: str) -> None:
        if not self.use_telegram:
            return
        from tiktok_live_recorder.upload.telegram import Telegram

        filename = Path(file_path).name
        self._record_telegram_upload(user, filename, "uploading", "Upload started")
        result = Telegram().upload(file_path)
        self._record_telegram_upload(
            user,
            filename,
            result.get("status", "error"),
            result.get("message", "Upload finished"),
        )

    def _is_user_busy(self, username: str) -> bool:
        entry = self._active_recordings.get(username)
        if not entry:
            return False
        return self._entry_still_active(entry)

    def _is_user_recording(self, username: str) -> bool:
        return self._is_user_busy(username)

    def _room_owner(self, room_id: str, *, exclude: str | None = None) -> str | None:
        for name, entry in self._active_recordings.items():
            if exclude and name == exclude:
                continue
            if entry.get("room_id") == room_id and self._entry_still_active(entry):
                return name
        return None

    def _spawn_recording_thread(self, username: str, room_id: str) -> None:
        thread = Thread(
            target=self._recording_worker,
            args=(username, room_id),
            daemon=False,
            name=f"record-{username}",
        )
        thread.start()
        stop_event = Event()
        self._user_stop_events[username] = stop_event
        self._active_recordings[username] = {
            "thread": thread,
            "room_id": room_id,
            "started_at": time.time(),
            "output_path": None,
            "bytes_written": 0,
            "status": "recording",
            "stop_event": stop_event,
        }
        self.record_activity(
            "recording",
            f"Started recording room {room_id}",
            username=username,
        )

    def start_recording_now(
        self,
        *,
        username: str | None = None,
        room_id: str | None = None,
    ) -> dict:
        if not username and not room_id:
            raise ValueError("username or room_id is required")

        if room_id and not username:
            username = self.tiktok.get_user_from_room_id(room_id)
        elif username and not room_id:
            room_id = self.tiktok.get_room_id_from_user(username.lstrip("@").strip())

        username = username.lstrip("@").strip()
        if not username or not room_id:
            raise ValueError("Could not resolve username and room_id")

        if self._is_user_busy(username):
            raise RuntimeError(f"@{username} is already recording")

        owner = self._room_owner(room_id, exclude=username)
        if owner:
            raise RuntimeError(f"Room is already being recorded by @{owner}")

        if not self.tiktok.is_room_alive(room_id, user=username):
            raise UserLiveError(f"@{username} is not currently live")

        self._spawn_recording_thread(username, room_id)
        return {"username": username, "room_id": room_id, "status": "started"}

    def _update_recording_entry(self, user: str, **fields) -> None:
        with self._state_lock:
            entry = self._active_recordings.get(user)
            if entry is not None:
                entry.update(fields)

    def _setup(self):
        """Resolve user/room data and validate prerequisites via network calls."""
        if self.mode == Mode.FOLLOWERS:
            self.check_country_blacklisted()

            self.sec_uid = self.tiktok.get_sec_uid()
            if self.sec_uid is None:
                raise TikTokRecorderError("Failed to retrieve sec_uid.")

            logger.info("Followers mode activated\n")
        elif self.mode == Mode.WATCHLIST:
            self.check_country_blacklisted()
            logger.info(f"Watching {len(self.users)} users: {', '.join(self.users)}\n")
        else:
            if self.url:
                self.user, self.room_id = self.tiktok.get_room_and_user_from_url(
                    self.url
                )

            if not self.user:
                self.user = self.tiktok.get_user_from_room_id(self.room_id)

            if not self.room_id:
                self.room_id = self.tiktok.get_room_id_from_user(self.user)

            self.check_country_blacklisted()

            logger.info(f"USERNAME: {self.user}" + ("\n" if not self.room_id else ""))
            if self.room_id:
                logger.info(
                    f"ROOM_ID:  {self.room_id}"
                    + (
                        "\n"
                        if not self.tiktok.is_room_alive(self.room_id, user=self.user)
                        else ""
                    )
                )

        # If proxy was used for the initial checks, switch to a direct connection
        # for the actual stream download to avoid proxy bottlenecks
        if self._proxy:
            self.tiktok = TikTokAPI(proxy=None, cookies=self._cookies)

    def run(self):
        """
        Resolves prerequisites and runs the recorder in the selected mode.
        """
        self._setup()
        self._install_signal_handlers()

        try:
            if self.mode == Mode.MANUAL:
                self.manual_mode()

            elif self.mode == Mode.AUTOMATIC:
                self.automatic_mode()

            elif self.mode == Mode.WATCHLIST:
                self.watchlist_mode()

            elif self.mode == Mode.FOLLOWERS:
                self.followers_mode()
        except KeyboardInterrupt:
            self.request_stop()
            logger.info("Interrupted — finalizing open recordings...")
        finally:
            if self._stopped_by_signal is not None:
                logger.info(
                    f"Signal {self._stopped_by_signal} received — stopping gracefully..."
                )
            self._shutdown_recordings()

    def _install_signal_handlers(self):
        def _handler(signum, frame):
            self._stopped_by_signal = signum
            self.request_stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                # Not in main thread, or unsupported on this platform.
                pass

    def manual_mode(self):
        if not self.tiktok.is_room_alive(self.room_id, user=self.user):
            raise UserLiveError(f"@{self.user}: {TikTokError.USER_NOT_CURRENTLY_LIVE}")

        self.start_recording(self.user, self.room_id)
        self._wait_for_user_pipeline(self.user)

    def _wait_for_user_pipeline(self, username: str, timeout: float = 3600.0) -> None:
        deadline = time.time() + timeout
        while self._is_user_busy(username) and time.time() < deadline:
            time.sleep(0.5)

    def automatic_mode(self):
        while not self._should_stop():
            try:
                self.room_id = self.tiktok.get_room_id_from_user(self.user)
                self.manual_mode()

            except (UserLiveError, LiveNotFound) as ex:
                logger.info(ex)
                logger.info(
                    f"Waiting {self.automatic_interval} minutes before recheck\n"
                )
                self._stop.wait(self.automatic_interval * TimeOut.ONE_MINUTE)

            except (ConnectionError, RequestException, HTTPException):
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                self._stop.wait(TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE)

    def _reload_watchlist_users(self) -> list[str]:
        """Reload usernames from the watchlist file when configured."""
        if not self.users_file:
            return self.users or []

        from tiktok_live_recorder.utils.utils import read_users

        loaded = read_users(self.users_file)
        previous = set(self.users or [])
        current = set(loaded)
        added = sorted(current - previous)
        removed = sorted(previous - current)
        if added:
            logger.info(
                "Watchlist updated — added: "
                + ", ".join(f"@{username}" for username in added)
            )
        if removed:
            logger.info(
                "Watchlist updated — removed: "
                + ", ".join(f"@{username}" for username in removed)
                + " (active recordings finish before being dropped)"
            )

        self.users = loaded
        return loaded

    def watchlist_mode(self):
        self._poll_users_loop(self._reload_watchlist_users, label="Watchlist")

    def followers_mode(self):
        self._poll_users_loop(
            lambda: self.tiktok.get_followers_list(self.sec_uid),
            label="Followers",
        )

    def _check_user_live(self, username: str) -> str | None:
        """Return room_id when the user is live, or None when offline."""
        for attempt in range(2):
            try:
                room_id = self.tiktok.get_room_id_from_user(username)
                if not room_id or not self.tiktok.is_room_alive(room_id, user=username):
                    return None
                return room_id
            except RequestException:
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                raise
        return None

    def _poll_user_order(self, users: list[str]) -> list[str]:
        """Return a shuffled copy so poll order varies each cycle."""
        ordered = list(users)
        if len(ordered) > 1:
            random.shuffle(ordered)
        return ordered

    def _log_poll_plan(self, label: str, poll_users: list[str]) -> None:
        count = len(poll_users)
        if count == 0:
            return
        if count == 1:
            logger.debug(f"{label} poll: checking @{poll_users[0]}")
            return
        logger.info(
            f"{label} poll: checking {count} users in shuffled order "
            f"({POLL_USER_DELAY_SECONDS}s spacing between users)"
        )
        logger.debug(f"{label} poll order: {', '.join(f'@{u}' for u in poll_users)}")

    def _poll_users_once(self, users, active_recordings, label):
        from tiktok_live_recorder.utils.utils import read_paused_users

        reset_warn = getattr(self.tiktok, "reset_tikrec_warn_flag", None)
        if callable(reset_warn):
            reset_warn()
        paused_users = read_paused_users()
        counts = {"recording": 0, "offline": 0, "started": 0, "error": 0, "skipped": 0}
        groups = {
            "offline": [],
            "recording": [],
            "finished": [],
            "errors": [],
            "skipped": [],
            "starting": [],
            "paused": [],
        }

        users_set = set(users)
        for username, entry in list(active_recordings.items()):
            if username in users_set:
                continue
            if self._entry_still_active(entry):
                groups["recording"].append(username)
                counts["recording"] += 1
                continue

            outcome = self._recording_results.pop(username, "ok")
            if outcome == "ok":
                groups["finished"].append(username)
            else:
                groups["errors"].append(username)
                counts["error"] += 1
            del active_recordings[username]

        poll_users = self._poll_user_order(users)
        self._log_poll_plan(label, poll_users)

        aborted = False
        if self._drain_poll_requests(label):
            logger.info(f"{label} poll restarting early (force check)")
            return active_recordings, True

        for poll_index, username in enumerate(poll_users):
            if (
                poll_index > 0
                and not self._should_stop()
                and POLL_USER_DELAY_SECONDS > 0
            ):
                time.sleep(POLL_USER_DELAY_SECONDS)

            if self._drain_poll_requests(label):
                aborted = True
                break

            if username in active_recordings:
                entry = active_recordings[username]
                if self._entry_still_active(entry):
                    status = entry.get("status", "recording")
                    if status in _POST_RECORD_STATUSES:
                        groups["recording"].append(username)
                    else:
                        groups["recording"].append(username)
                    counts["recording"] += 1
                    continue

                outcome = self._recording_results.pop(username, "ok")
                if outcome == "ok":
                    groups["finished"].append(username)
                else:
                    groups["errors"].append(username)
                    counts["error"] += 1
                del active_recordings[username]
                self._user_stop_events.pop(username, None)

            if self._should_stop():
                break

            if username.lower() in paused_users:
                groups["paused"].append(username)
                continue

            if username in self._checked_this_cycle:
                continue

            try:
                room_id = self._check_user_live(username)
                self._checked_this_cycle.add(username)

                if room_id is None:
                    groups["offline"].append(username)
                    counts["offline"] += 1
                    continue

                owner = next(
                    (
                        name
                        for name, entry in active_recordings.items()
                        if entry["room_id"] == room_id and entry["thread"].is_alive()
                    ),
                    None,
                )
                if owner:
                    groups["skipped"].append(f"@{username} (room @{owner})")
                    counts["skipped"] += 1
                    continue

                groups["starting"].append((username, room_id))
                counts["started"] += 1

            except TikTokRecorderError as e:
                self._checked_this_cycle.add(username)
                groups["errors"].append(f"{username} ({e})")
                counts["error"] += 1

            except RequestException as e:
                self._checked_this_cycle.add(username)
                logger.warning(f"  @{username}: network error during poll: {e}")
                groups["errors"].append(f"{username} (network error)")
                counts["error"] += 1

            except Exception as e:
                self._checked_this_cycle.add(username)
                logger.error(f"  @{username}: {e}", exc_info=True)
                groups["errors"].append(f"{username} (unexpected error)")
                counts["error"] += 1

        if aborted:
            logger.info(f"{label} poll restarting early (force check)")
            return active_recordings, True

        logger.info(f"--- {label} ({len(users)} users) ---")
        if groups["offline"]:
            logger.info(f"  offline:   {', '.join(f'@{u}' for u in groups['offline'])}")
        if groups["recording"]:
            logger.info(
                f"  recording: {', '.join(f'@{u}' for u in groups['recording'])}"
            )
        if groups["finished"]:
            logger.info(
                f"  finished:  {', '.join(f'@{u}' for u in groups['finished'])}"
            )
        if groups["starting"]:
            logger.info(
                f"  live:      {', '.join(f'@{u}' for u, _ in groups['starting'])}"
            )
        if groups["skipped"]:
            logger.info(f"  skipped:   {', '.join(groups['skipped'])}")
        if groups["paused"]:
            logger.info(f"  paused:    {', '.join(f'@{u}' for u in groups['paused'])}")
        if groups["errors"]:
            logger.info(f"  error:     {', '.join(groups['errors'])}")

        self._last_poll_at = time.time()
        self._poll_label = label
        self._last_poll_snapshot = {
            "offline": list(groups["offline"]),
            "recording": list(groups["recording"]),
            "finished": list(groups["finished"]),
            "errors": list(groups["errors"]),
            "skipped": list(groups["skipped"]),
            "paused": list(groups["paused"]),
            "starting": [
                {"username": username, "room_id": room_id}
                for username, room_id in groups["starting"]
            ],
        }

        for username, room_id in groups["starting"]:
            if self._should_stop():
                break
            self._spawn_recording_thread(username, room_id)
            active_recordings[username] = self._active_recordings[username]
            time.sleep(2.5)

        return active_recordings, False

    def _run_poll_cycle(self, users: list[str], label: str) -> bool:
        self._checked_this_cycle = set()
        self._begin_poll()
        self.record_activity("poll", f"{label} poll started")
        aborted = False
        try:
            self._active_recordings, aborted = self._poll_users_once(
                users, self._active_recordings, label
            )
        finally:
            self._end_poll()
            if not aborted:
                self.record_activity("poll", f"{label} poll finished")
        return aborted

    def _run_partial_poll_cycle(self, users: list[str], label: str) -> bool:
        if not users:
            return False
        if len(users) == 1:
            logger.info(f"{label} priority poll: checking @{users[0]}")
        else:
            logger.info(f"{label} priority poll: checking {len(users)} users")
        with self._state_lock:
            nested = self._poll_in_progress_depth > 0
        if not nested:
            self._begin_poll()
        self.record_activity("poll", f"Priority check for {len(users)} user(s)")
        try:
            self._active_recordings, aborted = self._poll_users_once(
                users, self._active_recordings, label
            )
            return aborted
        finally:
            if not nested:
                self._end_poll()

    def _poll_users_loop(self, get_users, label):
        self._active_recordings = {}

        while not self._should_stop():
            try:
                while True:
                    aborted = self._run_poll_cycle(get_users(), label)
                    if not aborted:
                        break
                    logger.info(f"{label} poll restarting immediately (force check)")

                if self._should_stop():
                    break

                logger.info(f"Waiting {self.automatic_interval} min · next check")
                self._wait_for_next_poll(
                    self.automatic_interval * TimeOut.ONE_MINUTE,
                    label=label,
                )

            except (UserLiveError, LiveNotFound) as ex:
                logger.info(ex)
                logger.info(
                    f"Waiting {self.automatic_interval} minutes before recheck\n"
                )
                self._wait_for_next_poll(
                    self.automatic_interval * TimeOut.ONE_MINUTE,
                    label=label,
                )

            except (ConnectionError, RequestException, HTTPException):
                logger.error(Error.CONNECTION_CLOSED_AUTOMATIC)
                self._wait_for_next_poll(
                    TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE,
                    label=label,
                )

    def _shutdown_recordings(self, timeout: float = 300.0):
        """Wait for recording threads and queued conversions after a stop request."""
        self.request_stop()
        active = getattr(self, "_active_recordings", {}) or {}
        if not active:
            return

        logger.info(
            f"Waiting for {len(active)} recording(s) to finalize (Ctrl+C again to abandon)..."
        )
        deadline = time.time() + timeout
        for username, entry in list(active.items()):
            thread = entry.get("thread")
            if thread is None:
                continue
            remaining = max(0.0, deadline - time.time())
            thread.join(timeout=remaining)
            if thread.is_alive():
                logger.warning(f"[@{username}] still finalizing after wait timeout")

        while self._active_recordings and time.time() < deadline:
            stats = self._convert_queue.stats()
            if stats["pending"] == 0 and stats["active"] == 0:
                break
            time.sleep(0.5)

        for username in list(self._active_recordings):
            outcome = self._recording_results.pop(username, "ok")
            if outcome == "ok":
                logger.info(f"[@{username}] finalized")
            else:
                logger.info(f"[@{username}] stopped with error")

    def _log_recording(self, user, message, level="info"):
        getattr(logger, level)(f"[@{user}] {message}")

    def _recording_worker(self, user, room_id):
        try:
            self.start_recording(user, room_id)
        except (UserLiveError, LiveNotFound) as ex:
            self._recording_results[user] = "error"
            self._log_recording(user, str(ex), "error")
            with self._state_lock:
                self._active_recordings.pop(user, None)
            self._user_stop_events.pop(user, None)
        except Exception as ex:
            self._recording_results[user] = "error"
            self._log_recording(user, f"Unexpected error: {ex}", "error")
            with self._state_lock:
                self._active_recordings.pop(user, None)
            self._user_stop_events.pop(user, None)
        finally:
            if self.mode in (Mode.WATCHLIST, Mode.FOLLOWERS):
                self._wake_poll_loop()

    def _enqueue_conversion(self, user: str, output: str) -> None:
        def on_start() -> None:
            self._update_recording_entry(
                user,
                status="converting",
                convert_progress={"percent": 0, "phase": "starting"},
            )

        def on_progress(progress: dict) -> None:
            self._update_recording_entry(user, convert_progress=progress)

        def on_complete(converted: bool, mp4_output: str) -> None:
            if converted and Path(mp4_output).is_file():
                self._update_recording_entry(
                    user, status="finished", convert_progress=None
                )
                self._maybe_upload_to_telegram(user, mp4_output)
                self._recording_results[user] = "ok"
            else:
                self._update_recording_entry(
                    user, status="convert_failed", convert_progress=None
                )
                self._recording_results[user] = "error"
            with self._state_lock:
                self._active_recordings.pop(user, None)
            self._user_stop_events.pop(user, None)
            self._wake_poll_loop(reason="conversion-finished")

        queue_position = self._convert_queue.enqueue(
            ConvertJob(
                user=user,
                output_path=output,
                bitrate=self.bitrate,
                ffmpeg_path=self.ffmpeg_path,
                on_progress=on_progress,
                on_start=on_start,
                on_complete=on_complete,
            )
        )
        self._update_recording_entry(
            user,
            status="convert_queued",
            convert_progress={"phase": "queued", "queue_position": queue_position},
        )

    def _build_output_path(self, user: str) -> str:
        filename = (
            f"TK_{user}_{time.strftime('%Y.%m.%d_%H-%M-%S', time.localtime())}_flv.mp4"
        )
        return str(output_dir_for_user(self.output, user) / filename)

    def _pick_next_stream_url(
        self, candidates: list[str], failed_urls: set[str]
    ) -> str | None:
        for url in candidates:
            if normalize_cdn_url(url) not in failed_urls:
                return url
        return None

    def _refresh_live_urls(self, room_id, user, fallback: list[str] | None = None):
        """
        Fetch fresh CDN candidates. If the room went offline mid-recording,
        treat that as an empty candidate list instead of aborting finalize.
        """
        try:
            return self.tiktok.get_live_url_candidates(room_id, user=user) or (
                list(fallback) if fallback else []
            )
        except (UserLiveError, LiveNotFound):
            return []

    def start_recording(self, user, room_id):
        """
        Start recording live
        """
        live_urls = self.tiktok.get_live_url_candidates(room_id, user=user)
        if not live_urls:
            raise LiveNotFound(TikTokError.RETRIEVE_LIVE_URL)

        output = self._build_output_path(user)
        self._update_recording_entry(
            user,
            output_path=output,
            status="recording",
            bytes_written=0,
            started_at=time.time(),
        )
        min_stream_bytes = 4096
        buffer_size = 64 * 1024
        failed_urls: set[str] = set()
        live_url = live_urls[0]
        max_empty_reconnects = 3
        empty_reconnects = 0
        last_reconnect_log = 0.0
        cdn_gone_streak = 0
        bytes_at_last_cdn_gone: int | None = None
        max_cdn_gone_streak = 6

        buffer = bytearray()
        bytes_written = 0
        connected_logged = False

        self._log_recording(user, f"→ {Path(output).name} (Ctrl+C to stop)")

        def _assume_live_on_check_error() -> bool:
            return bytes_written >= min_stream_bytes

        try:
            with open(output, "wb") as out_file:
                stop_recording = False
                while not stop_recording and not self._should_stop_user(user):
                    stream_ended = False
                    alive_check_interval = 30
                    last_alive_check = time.time()
                    bytes_before = bytes_written

                    try:
                        if not self.tiktok.check_alive(
                            room_id,
                            assume_live_on_error=_assume_live_on_check_error(),
                        ):
                            self._log_recording(
                                user, "User is no longer live. Stopping recording."
                            )
                            break

                        last_alive_check = time.time()
                        start_time = time.time()
                        for chunk in self.tiktok.download_live_stream(live_url):
                            if self._should_stop_user(user):
                                self._log_recording(
                                    user, "Stop requested — finalizing recording."
                                )
                                stop_recording = True
                                self._update_recording_entry(user, status="stopping")
                                break

                            buffer.extend(chunk)
                            bytes_written += len(chunk)
                            self._update_recording_entry(
                                user, bytes_written=bytes_written
                            )
                            if (
                                not connected_logged
                                and bytes_written >= min_stream_bytes
                            ):
                                connected_logged = True
                                empty_reconnects = 0
                                self._log_recording(
                                    user,
                                    f"stream connected ({bytes_written // 1024} KB)",
                                )
                            if len(buffer) >= buffer_size:
                                out_file.write(buffer)
                                buffer.clear()
                                out_file.flush()

                            now = time.time()
                            if now - last_alive_check >= alive_check_interval:
                                last_alive_check = now
                                if not self.tiktok.check_alive(
                                    room_id,
                                    assume_live_on_error=True,
                                ):
                                    self._log_recording(
                                        user,
                                        "User is no longer live. Stopping recording.",
                                    )
                                    stop_recording = True
                                    break

                            elapsed_time = now - start_time
                            if self.duration and elapsed_time >= self.duration:
                                stop_recording = True
                                break
                        else:
                            stream_ended = True

                        if stop_recording or self._should_stop_user(user):
                            break

                        if stream_ended:
                            gained = bytes_written - bytes_before

                            # Never got a usable stream from this URL — try another.
                            if bytes_written < min_stream_bytes:
                                failed_urls.add(normalize_cdn_url(live_url))
                                refreshed = self._refresh_live_urls(
                                    room_id, user, fallback=live_urls
                                )
                                nxt = self._pick_next_stream_url(refreshed, failed_urls)
                                if nxt:
                                    live_url = nxt
                                    logger.debug(
                                        f"[@{user}] empty stream; trying next CDN candidate"
                                    )
                                    continue
                                break

                            if not self.tiktok.check_alive(
                                room_id,
                                assume_live_on_error=True,
                            ):
                                self._log_recording(
                                    user,
                                    "User is no longer live. Stopping recording.",
                                )
                                break

                            # Connected before, but this pull returned nothing useful —
                            # avoid a tight reconnect/log spin.
                            if gained < min_stream_bytes:
                                empty_reconnects += 1
                                if empty_reconnects >= max_empty_reconnects:
                                    self._log_recording(
                                        user,
                                        "Stream ended (no more data after reconnects). "
                                        "Stopping recording.",
                                    )
                                    break
                            else:
                                empty_reconnects = 0

                            now = time.time()
                            if now - last_reconnect_log >= 30:
                                self._log_recording(
                                    user,
                                    "Stream disconnected; reconnecting...",
                                    "warning",
                                )
                                last_reconnect_log = now
                            time.sleep(min(2 * max(empty_reconnects, 1), 10))

                    except ConnectionError as ex:
                        if _assume_live_on_check_error():
                            self._log_recording(
                                user, f"Network hiccup, retrying: {ex}", "warning"
                            )
                            time.sleep(2)
                            continue
                        if (
                            self.mode in (Mode.AUTOMATIC, Mode.WATCHLIST)
                            and not self._should_stop()
                        ):
                            self._log_recording(
                                user, str(Error.CONNECTION_CLOSED_AUTOMATIC), "error"
                            )
                            self._stop.wait(
                                TimeOut.CONNECTION_CLOSED * TimeOut.ONE_MINUTE
                            )
                            continue

                    except (RequestException, HTTPException) as ex:
                        if _is_stream_url_gone(ex):
                            failed_urls.add(normalize_cdn_url(live_url))
                            if bytes_at_last_cdn_gone == bytes_written:
                                cdn_gone_streak += 1
                            else:
                                cdn_gone_streak = 1
                            bytes_at_last_cdn_gone = bytes_written
                            if cdn_gone_streak >= max_cdn_gone_streak:
                                self._log_recording(
                                    user,
                                    "CDN URL gone repeatedly with no new data. "
                                    "Stopping recording.",
                                )
                                break
                            if not self.tiktok.check_alive(
                                room_id,
                                assume_live_on_error=True,
                            ):
                                self._log_recording(
                                    user,
                                    "Stream ended (CDN URL gone). Stopping recording.",
                                )
                                break

                            refreshed = self._refresh_live_urls(room_id, user)
                            nxt = self._pick_next_stream_url(refreshed, failed_urls)
                            if nxt:
                                live_url = nxt
                                self._log_recording(
                                    user,
                                    f"CDN URL gone; trying next candidate "
                                    f"({len(failed_urls)} failed, "
                                    f"{len(refreshed)} available)...",
                                )
                                continue

                            self._log_recording(
                                user,
                                "CDN URL gone; all refreshed candidates exhausted. "
                                "Stopping recording.",
                            )
                            break

                        self._log_recording(
                            user, f"Network hiccup, retrying: {ex}", "warning"
                        )
                        time.sleep(2)
                        continue

                    except (UserLiveError, LiveNotFound) as ex:
                        # Can escape from nested API calls in some paths; finalize below.
                        self._log_recording(
                            user,
                            f"Stream ended ({ex}). Stopping recording.",
                        )
                        break

                    except KeyboardInterrupt:
                        self.request_stop()
                        self._log_recording(user, "Recording stopped by user.")
                        break

                    except Exception as ex:
                        self._log_recording(
                            user,
                            f"Unexpected error during recording: {ex}",
                            "error",
                        )
                        break

                    finally:
                        if buffer:
                            out_file.write(buffer)
                            buffer.clear()
                        out_file.flush()

        except (UserLiveError, LiveNotFound) as ex:
            # Exceptions raised inside an except-handler bypass sibling handlers;
            # if we already captured usable data, fall through to convert.
            if bytes_written < min_stream_bytes:
                Path(output).unlink(missing_ok=True)
                raise
            self._log_recording(
                user,
                f"Stream ended ({ex}). Finalizing recording.",
            )

        if bytes_written < min_stream_bytes:
            Path(output).unlink(missing_ok=True)
            raise LiveNotFound(TikTokError.RETRIEVE_LIVE_URL)

        self._log_recording(user, f"Recording finished: {Path(output).resolve()}\n")
        self._enqueue_conversion(user, output)

    def active_recording_output_paths(self) -> set[str]:
        active: set[str] = set()
        with self._state_lock:
            for entry in self._active_recordings.values():
                status = entry.get("status")
                if status not in _BUSY_STATUSES:
                    continue
                output_path = entry.get("output_path")
                if output_path:
                    try:
                        active.add(str(Path(output_path).resolve()))
                    except OSError:
                        active.add(str(output_path))
        return active

    def move_leftover_flvs(self) -> dict:
        from tiktok_live_recorder.utils.utils import default_to_fix_dir
        from tiktok_live_recorder.web.media import move_orphan_flv_files

        return move_orphan_flv_files(
            self._output_base(),
            self.output,
            self.active_recording_output_paths(),
            default_to_fix_dir(),
        )

    def _output_base(self) -> Path:
        from tiktok_live_recorder.utils.utils import default_output_base

        return default_output_base()

    def check_country_blacklisted(self):
        is_blacklisted = self.tiktok.is_country_blacklisted()
        if not is_blacklisted:
            return False

        if self.room_id is None:
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED)

        if self.mode in (Mode.AUTOMATIC, Mode.WATCHLIST):
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED_AUTO_MODE)

        elif self.mode == Mode.FOLLOWERS:
            raise TikTokRecorderError(TikTokError.COUNTRY_BLACKLISTED_FOLLOWERS_MODE)

        return is_blacklisted
