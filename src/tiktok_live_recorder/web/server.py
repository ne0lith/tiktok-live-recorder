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
        self._config = config
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
        self._thread.start()
        logger.info(
            f"Web dashboard at http://{self._config.web_host}:{self._config.web_port}"
        )

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout=5.0)


def start_web_server(recorder: TikTokRecorder, config: RecorderConfig) -> WebServer:
    server = WebServer(recorder, config)
    server.start()
    return server
