from pathlib import Path
from unittest.mock import MagicMock

from tiktok_live_recorder.core.convert_queue import ConvertJob, ConvertQueue


def test_convert_queue_runs_job_and_reports_stats(monkeypatch):
    convert = MagicMock(return_value=True)
    monkeypatch.setattr(
        "tiktok_live_recorder.core.convert_queue.VideoManagement.convert_flv_to_mp4",
        convert,
    )

    completed: list[bool] = []
    started: list[bool] = []
    queue = ConvertQueue(max_concurrent=1)

    def on_start() -> None:
        started.append(True)

    def on_complete(success: bool, _mp4_output: str) -> None:
        completed.append(success)

    flv = Path("TK_user_2026.01.01_12-00-00_flv.mp4")
    mp4 = Path("TK_user_2026.01.01_12-00-00.mp4")
    mp4.write_bytes(b"mp4")

    queue.enqueue(
        ConvertJob(
            user="user",
            output_path=str(flv),
            bitrate=None,
            ffmpeg_path=None,
            on_progress=None,
            on_start=on_start,
            on_complete=on_complete,
        )
    )

    import time

    # Wait for async worker
    deadline = 5.0
    start = time.time()
    while time.time() - start < deadline:
        stats = queue.stats()
        if stats["pending"] == 0 and stats["active"] == 0 and completed:
            break
        time.sleep(0.05)

    assert started == [True]
    assert completed == [True]
    convert.assert_called_once()
    mp4.unlink(missing_ok=True)


def test_convert_queue_limits_active_workers(monkeypatch):
    active = {"count": 0, "max": 0}
    lock = __import__("threading").Lock()
    release_first = __import__("threading").Event()

    def slow_convert(*_args, **_kwargs):
        with lock:
            active["count"] += 1
            active["max"] = max(active["max"], active["count"])
        release_first.wait(timeout=2)
        with lock:
            active["count"] -= 1
        return False

    monkeypatch.setattr(
        "tiktok_live_recorder.core.convert_queue.VideoManagement.convert_flv_to_mp4",
        slow_convert,
    )

    queue = ConvertQueue(max_concurrent=1)
    done = []

    def make_job(name: str) -> ConvertJob:
        return ConvertJob(
            user=name,
            output_path=f"TK_{name}_flv.mp4",
            bitrate=None,
            ffmpeg_path=None,
            on_progress=None,
            on_start=None,
            on_complete=lambda *_args, _name=name: done.append(_name),
        )

    queue.enqueue(make_job("a"))
    queue.enqueue(make_job("b"))
    import time

    time.sleep(0.2)
    assert queue.stats()["active"] <= 1
    release_first.set()

    deadline = time.time() + 5
    while time.time() < deadline and len(done) < 2:
        time.sleep(0.05)

    assert len(done) == 2
    assert active["max"] == 1
