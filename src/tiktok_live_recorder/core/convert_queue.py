from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tiktok_live_recorder.utils.logger_manager import logger
from tiktok_live_recorder.utils.video_management import VideoManagement

ConvertProgressCallback = Callable[[dict[str, Any]], None]
ConvertCompleteCallback = Callable[[bool, str], None]


@dataclass
class ConvertJob:
    user: str
    output_path: str
    bitrate: str | None
    ffmpeg_path: str | None
    on_progress: ConvertProgressCallback | None
    on_start: Callable[[], None] | None
    on_complete: ConvertCompleteCallback
    mode: str = "flv"


class ConvertQueue:
    """FIFO queue with a bounded number of concurrent ffmpeg conversions."""

    def __init__(self, max_concurrent: int = 1) -> None:
        self._lock = threading.Lock()
        self._max_concurrent = max(1, max_concurrent)
        self._semaphore = threading.Semaphore(self._max_concurrent)
        self._jobs: queue.Queue[ConvertJob | None] = queue.Queue()
        self._pending = 0
        self._active = 0
        self._shutdown = False
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop,
            name="convert-dispatcher",
            daemon=True,
        )
        self._dispatcher.start()

    def set_max_concurrent(self, max_concurrent: int) -> None:
        max_concurrent = max(1, max_concurrent)
        with self._lock:
            if max_concurrent == self._max_concurrent:
                return
            self._max_concurrent = max_concurrent
            self._semaphore = threading.Semaphore(max_concurrent)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "pending": self._pending,
                "active": self._active,
                "max_concurrent": self._max_concurrent,
            }

    def enqueue(self, job: ConvertJob) -> int:
        with self._lock:
            self._pending += 1
            position = self._pending
        self._jobs.put(job)
        return position

    def shutdown(self, *, wait: bool = True, timeout: float = 600.0) -> None:
        self._shutdown = True
        self._jobs.put(None)
        if wait and self._dispatcher.is_alive():
            self._dispatcher.join(timeout=timeout)

    def _dispatch_loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                self._jobs.task_done()
                break
            worker = threading.Thread(
                target=self._run_job,
                args=(job,),
                name=f"convert-{job.user}",
                daemon=True,
            )
            worker.start()

    def _run_job(self, job: ConvertJob) -> None:
        self._semaphore.acquire()
        try:
            with self._lock:
                self._pending = max(0, self._pending - 1)
                self._active += 1
            if job.on_start:
                job.on_start()
            if job.mode == "repair":
                mp4_output = job.output_path
                success = VideoManagement.repair_mp4_file(
                    job.output_path,
                    job.bitrate,
                    job.ffmpeg_path,
                    on_progress=job.on_progress,
                )
            else:
                mp4_output = job.output_path.replace("_flv.mp4", ".mp4")
                converted = VideoManagement.convert_flv_to_mp4(
                    job.output_path,
                    job.bitrate,
                    job.ffmpeg_path,
                    on_progress=job.on_progress,
                )
                success = converted and Path(mp4_output).is_file()
            if not success:
                logger.warning(
                    "[@%s] Conversion failed; left raw recording at %s",
                    job.user,
                    job.output_path,
                )
            job.on_complete(success, mp4_output)
        except Exception as exc:
            logger.error("[@%s] Conversion error: %s", job.user, exc, exc_info=True)
            mp4_output = (
                job.output_path
                if job.mode == "repair"
                else job.output_path.replace("_flv.mp4", ".mp4")
            )
            job.on_complete(False, mp4_output)
        finally:
            with self._lock:
                self._active = max(0, self._active - 1)
            self._semaphore.release()
            self._jobs.task_done()
