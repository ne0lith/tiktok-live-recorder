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


def runtime_settings_path() -> str:
    return str(_ensure_config_file("runtime_settings.json"))


def default_runtime_settings() -> dict:
    return {
        "automatic_interval_minutes": 5,
        "use_telegram": False,
        "max_concurrent_converts": 1,
    }


def read_runtime_settings() -> dict:
    from tiktok_live_recorder.utils.logger_manager import logger

    settings = default_runtime_settings()
    path = runtime_settings_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return settings
    except json.JSONDecodeError as exc:
        logger.error(f"runtime settings at {path} are invalid JSON: {exc}")
        return settings

    if not isinstance(data, dict):
        logger.error(f"runtime settings at {path} must be a JSON object")
        return settings

    if isinstance(data.get("automatic_interval_minutes"), int):
        settings["automatic_interval_minutes"] = max(
            1, data["automatic_interval_minutes"]
        )
    if isinstance(data.get("use_telegram"), bool):
        settings["use_telegram"] = data["use_telegram"]
    if isinstance(data.get("max_concurrent_converts"), int):
        settings["max_concurrent_converts"] = max(1, data["max_concurrent_converts"])
    return settings


def write_runtime_settings(settings: dict) -> None:
    path = runtime_settings_path()
    config_dir().mkdir(parents=True, exist_ok=True)
    payload = default_runtime_settings()
    if isinstance(settings.get("automatic_interval_minutes"), int):
        payload["automatic_interval_minutes"] = max(
            1, settings["automatic_interval_minutes"]
        )
    if isinstance(settings.get("use_telegram"), bool):
        payload["use_telegram"] = settings["use_telegram"]
    if isinstance(settings.get("max_concurrent_converts"), int):
        payload["max_concurrent_converts"] = max(1, settings["max_concurrent_converts"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def default_output_base() -> Path:
    return repo_root_path() / "output"


def default_to_fix_dir() -> Path:
    return repo_root_path() / "to_fix"


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


def watchlist_state_path() -> str:
    return str(config_dir() / "watchlist_state.json")


def user_identities_path() -> str:
    return str(config_dir() / "user_identities.json")


def read_user_identities(file_path: str | None = None) -> dict[str, dict]:
    """Load auto-managed watchlist identity map: original handle -> {secUid, uniqueId}."""
    from tiktok_live_recorder.utils.logger_manager import logger

    path = file_path or user_identities_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        logger.error(f"user identities at {path} are invalid JSON: {exc}")
        return {}

    if not isinstance(data, dict):
        logger.error(f"user identities at {path} must be a JSON object")
        return {}

    result: dict[str, dict] = {}
    for key, value in data.items():
        if not key or not isinstance(key, str) or not isinstance(value, dict):
            continue
        original = key.lstrip("@").strip()
        if not original:
            continue
        entry: dict[str, str] = {}
        unique_id = value.get("uniqueId") or value.get("unique_id")
        sec_uid = value.get("secUid") or value.get("sec_uid")
        if unique_id and str(unique_id).strip():
            entry["uniqueId"] = str(unique_id).lstrip("@").strip()
        if sec_uid and str(sec_uid).strip():
            entry["secUid"] = str(sec_uid).strip()
        if entry:
            result[original] = entry
    return result


def write_user_identities(
    identities: dict[str, dict], file_path: str | None = None
) -> None:
    path = file_path or user_identities_path()
    config_dir().mkdir(parents=True, exist_ok=True)
    payload: dict[str, dict[str, str]] = {}
    for key, value in identities.items():
        if not key or not isinstance(value, dict):
            continue
        original = str(key).lstrip("@").strip()
        if not original:
            continue
        entry: dict[str, str] = {}
        unique_id = value.get("uniqueId") or value.get("unique_id")
        sec_uid = value.get("secUid") or value.get("sec_uid")
        if unique_id and str(unique_id).strip():
            entry["uniqueId"] = str(unique_id).lstrip("@").strip()
        if sec_uid and str(sec_uid).strip():
            entry["secUid"] = str(sec_uid).strip()
        if entry:
            payload[original] = entry
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def get_user_identity(
    original: str, identities: dict[str, dict] | None = None
) -> dict | None:
    """Look up identity by original watchlist name (case-insensitive fallback)."""
    handle = original.lstrip("@").strip()
    if not handle:
        return None
    data = identities if identities is not None else read_user_identities()
    if handle in data:
        return data[handle]
    lower = handle.lower()
    for key, value in data.items():
        if key.lower() == lower:
            return value
    return None


def upsert_user_identity(
    original: str,
    *,
    unique_id: str | None = None,
    sec_uid: str | None = None,
    file_path: str | None = None,
) -> dict:
    """Create or update identity for a watchlist username. Returns the stored entry."""
    handle = original.lstrip("@").strip()
    identities = read_user_identities(file_path)
    # Preserve existing key casing when matching case-insensitively.
    key = handle
    for existing in identities:
        if existing.lower() == handle.lower():
            key = existing
            break
    entry = dict(identities.get(key) or {})
    if unique_id and str(unique_id).strip():
        entry["uniqueId"] = str(unique_id).lstrip("@").strip()
    if sec_uid and str(sec_uid).strip():
        entry["secUid"] = str(sec_uid).strip()
    identities[key] = entry
    write_user_identities(identities, file_path)
    return entry


def remove_user_identity(original: str, file_path: str | None = None) -> None:
    handle = original.lstrip("@").strip()
    if not handle:
        return
    identities = read_user_identities(file_path)
    keys = [k for k in identities if k == handle or k.lower() == handle.lower()]
    if not keys:
        return
    for key in keys:
        del identities[key]
    write_user_identities(identities, file_path)


def prune_user_identities(
    keep_usernames: list[str] | set[str], file_path: str | None = None
) -> None:
    """Drop identity entries whose original handle is no longer on the watchlist."""
    keep = {
        u.lstrip("@").strip().lower() for u in keep_usernames if u and str(u).strip()
    }
    identities = read_user_identities(file_path)
    pruned = {k: v for k, v in identities.items() if k.lower() in keep}
    if len(pruned) != len(identities):
        write_user_identities(pruned, file_path)


def read_paused_users(file_path: str | None = None) -> set[str]:
    """Load paused usernames from the auto-managed watchlist state file."""
    from tiktok_live_recorder.utils.logger_manager import logger

    path = file_path or watchlist_state_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return set()
    except json.JSONDecodeError as exc:
        logger.error(f"watchlist state at {path} is invalid JSON: {exc}")
        return set()

    if not isinstance(data, dict):
        logger.error(f"watchlist state at {path} must be a JSON object")
        return set()

    raw = data.get("paused", [])
    if not isinstance(raw, list):
        return set()
    return {u.lstrip("@").strip().lower() for u in raw if u and str(u).strip()}


def write_paused_users(paused: set[str], file_path: str | None = None) -> None:
    path = file_path or watchlist_state_path()
    config_dir().mkdir(parents=True, exist_ok=True)
    normalized = sorted({u.lstrip("@").strip() for u in paused if u and str(u).strip()})
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"paused": normalized}, f, indent=2)
        f.write("\n")


def _normalize_username(username: str) -> str:
    return username.lstrip("@").strip()


def _load_users_document(file_path: str) -> tuple[list[str], list | dict]:
    """Return usernames and the raw JSON document for format-preserving writes."""
    from tiktok_live_recorder.utils.logger_manager import logger

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return [], {"users": []}
    except json.JSONDecodeError as exc:
        logger.error(f"users file at {file_path} is invalid JSON: {exc}")
        return [], {"users": []}

    if isinstance(data, list):
        users = [_normalize_username(u) for u in data if u and str(u).strip()]
        return users, data
    if isinstance(data, dict):
        raw = data.get("users", [])
        if not isinstance(raw, list):
            raw = []
        users = [_normalize_username(u) for u in raw if u and str(u).strip()]
        return users, data

    logger.error(
        f"users file at {file_path} must be a list or an object with a 'users' key"
    )
    return [], {"users": []}


def write_users_document(
    file_path: str, users: list[str], document: list | dict
) -> None:
    """Write usernames back while preserving the original JSON shape."""
    normalized = [_normalize_username(u) for u in users if u and str(u).strip()]
    config_dir().mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        if isinstance(document, list):
            json.dump(normalized, f, indent=2)
        else:
            payload = dict(document)
            payload["users"] = normalized
            json.dump(payload, f, indent=2)
        f.write("\n")


def add_user_to_file(file_path: str, username: str) -> list[str]:
    users, document = _load_users_document(file_path)
    normalized = _normalize_username(username)
    if normalized and normalized not in users:
        users.append(normalized)
        write_users_document(file_path, users, document)
    return users


def remove_user_from_file(file_path: str, username: str) -> list[str]:
    users, document = _load_users_document(file_path)
    normalized = _normalize_username(username)
    users = [u for u in users if u != normalized]
    write_users_document(file_path, users, document)
    return users


def write_cookies(cookies: dict) -> None:
    path = cookies_file_path()
    config_dir().mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
        f.write("\n")


def write_telegram_config(config: dict) -> None:
    path = telegram_file_path()
    config_dir().mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


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
