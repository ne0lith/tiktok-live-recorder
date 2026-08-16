from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import uvicorn

from tiktok_live_recorder.utils.logger_manager import logger
from tiktok_live_recorder.web.app import create_app

if TYPE_CHECKING:
    from tiktok_live_recorder.core.tiktok_recorder import TikTokRecorder
    from tiktok_live_recorder.utils.recorder_config import RecorderConfig


class WebServer:
    def __init__(self, recorder: TikTokRecorder, config: RecorderConfig):
        self._recorder = recorder
        self._config = config
        self._codec_stop = threading.Event()
        self._codec_thread: threading.Thread | None = None
        self._server = uvicorn.Server(
            uvicorn.Config(
                create_app(recorder, config),
                host=config.web_host,
                port=config.web_port,
                log_level="warning",
                access_log=False,
            )
        )
        self._thread = threading.Thread(
            target=self._server.run,
            name="web-dashboard",
            daemon=True,
        )

    def start(self) -> None:
        self._start_codec_warmup()
        self._thread.start()
        logger.info(
            f"Web dashboard at http://{self._config.web_host}:{self._config.web_port}"
        )

    def _start_codec_warmup(self) -> None:
        from tiktok_live_recorder.utils.ffmpeg_setup import ffprobe_for
        from tiktok_live_recorder.utils.utils import default_output_base
        from tiktok_live_recorder.web.media import (
            configure_codec_index,
            start_codec_warmup_worker,
        )

        output_base = default_output_base()
        custom_output = self._config.output
        configure_codec_index(output_base, custom_output)
        ffmpeg_path = getattr(self._recorder, "ffmpeg_path", None)
        probe = ffprobe_for(ffmpeg_path) if ffmpeg_path else "ffprobe"
        active = set()
        getter = getattr(self._recorder, "active_recording_output_paths", None)
        if callable(getter):
            active = getter()
        self._codec_thread = start_codec_warmup_worker(
            output_base,
            custom_output,
            probe,
            self._codec_stop,
            active_output_paths=active,
        )

    def stop(self) -> None:
        self._codec_stop.set()
        self._server.should_exit = True
        if self._codec_thread is not None and self._codec_thread.is_alive():
            self._codec_thread.join(timeout=2.0)
        if self._thread.is_alive():
            self._thread.join(timeout=5.0)


def start_web_server(recorder: TikTokRecorder, config: RecorderConfig) -> WebServer:
    server = WebServer(recorder, config)
    server.start()
    return server
