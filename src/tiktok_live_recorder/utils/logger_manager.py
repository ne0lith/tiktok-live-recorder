import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_FILE = "tiktok-recorder.log"


class MaxLevelFilter(logging.Filter):
    """
    Filter that only allows log records up to a specified maximum level.
    """

    def __init__(self, max_level):
        super().__init__()
        self.max_level = max_level

    def filter(self, record):
        return record.levelno <= self.max_level


def resolve_log_file_path() -> Path:
    env_path = os.environ.get("TIKTOK_RECORDER_LOG_FILE")
    if env_path:
        return Path(env_path)
    return Path(DEFAULT_LOG_FILE)


def get_log_file_path() -> Path:
    for handler in LoggerManager().logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            return Path(handler.baseFilename)
    return resolve_log_file_path()


class LoggerManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LoggerManager, cls).__new__(cls)
            cls._instance.logger = None
            cls._instance.setup_logger()
        return cls._instance

    def setup_logger(self):
        if self.logger is None:
            self.logger = logging.getLogger("logger")
            self.logger.setLevel(logging.DEBUG)

            fmt_datefmt = "%Y-%m-%d %H:%M:%S"

            # 1) Console INFO handler (stdout)
            info_handler = logging.StreamHandler()
            info_handler.setLevel(logging.INFO)
            info_handler.setFormatter(
                logging.Formatter("[*] %(asctime)s - %(message)s", fmt_datefmt)
            )
            info_handler.addFilter(MaxLevelFilter(logging.INFO))
            self.logger.addHandler(info_handler)

            # 2) Console ERROR handler (stderr)
            error_handler = logging.StreamHandler()
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(
                logging.Formatter("[!] %(asctime)s - %(message)s", fmt_datefmt)
            )
            self.logger.addHandler(error_handler)

            # 3) File handler — DEBUG level, includes full stack traces
            #    Rotates at 5 MB, keeps 3 backups
            log_path = resolve_log_file_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(message)s", fmt_datefmt
                )
            )
            self.logger.addHandler(file_handler)


logger = LoggerManager().logger
