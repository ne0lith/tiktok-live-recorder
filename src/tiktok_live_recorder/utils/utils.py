import json
import os
import shutil
from pathlib import Path

from tiktok_live_recorder.utils.version import banner_text


def banner() -> None:
    """
    Prints a banner with the name of the tool and its version number.
    """
    print(banner_text(), flush=True)


def app_root_path() -> Path:
    """Source root directory containing the package (src/ in dev)."""
    return Path(__file__).resolve().parents[2]


def repo_root_path() -> Path:
    """Project root directory."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "config").is_dir() or (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def config_dir() -> Path:
    """Directory for user configuration files."""
    env_path = os.environ.get("TIKTOK_RECORDER_CONFIG_DIR")
    if env_path:
        return Path(env_path)
    return repo_root_path() / "config"


def _config_file_path(name: str) -> Path:
    return config_dir() / name


def _ensure_config_file(name: str) -> Path:
    """
    Ensure a config file exists, bootstrapping from its .example template if missing.
    """
    from tiktok_live_recorder.utils.logger_manager import logger

    path = _config_file_path(name)
    example = config_dir() / f"{name}.example"
    config_dir().mkdir(parents=True, exist_ok=True)

    if path.exists():
        return path

    if example.exists():
        shutil.copy2(example, path)
        logger.info(f"Created {path} from template {example}")
        return path

    logger.warning(
        f"Config file {path} not found and no template at {example}. "
        "Create the file manually."
    )
    return path


def cookies_file_path() -> str:
    return str(_ensure_config_file("cookies.json"))


def users_file_path() -> str:
    return str(_ensure_config_file("users.json"))


def telegram_file_path() -> str:
    return str(_ensure_config_file("telegram.json"))


def default_output_base() -> Path:
    return repo_root_path() / "output"


def output_dir_for_user(base: str | Path | None, username: str) -> Path:
    """Return (and create) the output directory for a recording."""
    if base is None:
        out_dir = default_output_base() / username.lstrip("@")
    else:
        out_dir = Path(base)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _cookie_value(cookies: dict | None, key: str) -> str:
    if not cookies:
        return ""
    return str(cookies.get(key, "")).strip()


def has_session_cookie(cookies: dict | None) -> bool:
    if not cookies:
        return False
    return bool(
        _cookie_value(cookies, "sessionid") or _cookie_value(cookies, "sessionid_ss")
    )


def cookie_key_summary(cookies: dict | None) -> str:
    if not cookies:
        return "none"
    tracked = ("sessionid", "sessionid_ss", "tt-target-idc")
    parts = []
    for key in tracked:
        parts.append(f"{key}={'yes' if _cookie_value(cookies, key) else 'no'}")
    for key in sorted(cookies):
        if key not in tracked:
            parts.append(f"{key}=yes")
    return ", ".join(parts)


def log_cookie_status(cookies: dict | None) -> None:
    from tiktok_live_recorder.utils.logger_manager import logger

    path = cookies_file_path()
    if cookies is None:
        logger.warning(f"cookies.json not loaded ({path})")
        return
    if has_session_cookie(cookies):
        logger.info(f"Loaded cookies.json from {path} ({cookie_key_summary(cookies)})")
        if _cookie_value(cookies, "sessionid_ss") and not _cookie_value(
            cookies, "sessionid"
        ):
            logger.warning(
                "Only sessionid_ss is set. Add sessionid from browser cookies for better "
                "WAF and restricted-live access."
            )
    else:
        logger.warning(
            f"Loaded cookies.json from {path} but sessionid and sessionid_ss are both "
            "missing or empty. Login-required streams will fail until you add them."
        )


def read_cookies():
    """
    Loads the config file and returns it.
    """
    from tiktok_live_recorder.utils.logger_manager import logger

    config_path = cookies_file_path()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(
            f"cookies.json not found at {config_path}. "
            "Login-required streams will fail until you create it."
        )
        return {}
    except json.JSONDecodeError as exc:
        logger.error(f"cookies.json at {config_path} is invalid JSON: {exc}")
        return {}


def read_users(file_path: str | None = None) -> list[str]:
    """
    Load usernames from a JSON file (list or {"users": [...]}).
    """
    from tiktok_live_recorder.utils.logger_manager import logger

    path = file_path or users_file_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        logger.error(f"users file at {path} is invalid JSON: {exc}")
        return []

    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get("users", [])
    else:
        logger.error(
            f"users file at {path} must be a list or an object with a 'users' key"
        )
        return []

    return [u.lstrip("@").strip() for u in raw if u and str(u).strip()]


def read_telegram_config():
    """
    Loads the telegram config file and returns it.
    """
    config_path = telegram_file_path()
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_termux() -> bool:
    """
    Checks if the script is running in Termux.

    Returns:
        bool: True if running in Termux, False otherwise.
    """
    import distro
    import platform

    return platform.system().lower() == "linux" and distro.like() == ""


def is_windows() -> bool:
    """
    Checks if the script is running on Windows.

    Returns:
        bool: True if running on Windows, False otherwise.
    """
    import platform

    return platform.system().lower() == "windows"


def is_linux() -> bool:
    """
    Checks if the script is running on Linux.

    Returns:
        bool: True if running on Linux, False otherwise.
    """
    import platform

    return platform.system().lower() == "linux"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class InstanceLock:
    """Prevent two recorder processes from running against the same output directory."""

    def __init__(self, directory: str | None):
        self.lock_dir = Path(directory or Path.cwd())
        self.lock_path = self.lock_dir / ".tiktok-recorder.lock"
        self._fd: int | None = None

    def acquire(self) -> None:
        from tiktok_live_recorder.utils.custom_exceptions import TikTokRecorderError
        from tiktok_live_recorder.utils.logger_manager import logger

        self.lock_dir.mkdir(parents=True, exist_ok=True)

        if self.lock_path.exists():
            try:
                existing_pid = int(self.lock_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                existing_pid = 0

            if _pid_alive(existing_pid):
                raise TikTokRecorderError(
                    f"Another recorder is already running (PID {existing_pid}). "
                    "Stop it before starting a new one, or you may get duplicate "
                    "recordings for the same user."
                )
            logger.warning(
                f"Removing stale lock file at {self.lock_path} (PID {existing_pid})."
            )
            self.lock_path.unlink(missing_ok=True)

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            self._fd = os.open(self.lock_path, flags)
        except FileExistsError as exc:
            raise TikTokRecorderError(
                "Another recorder is already running for this output directory."
            ) from exc

        os.write(self._fd, str(os.getpid()).encode("utf-8"))

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        self.lock_path.unlink(missing_ok=True)
