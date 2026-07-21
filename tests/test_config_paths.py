import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.utils import (  # noqa: E402
    _ensure_config_file,
    config_dir,
    cookies_file_path,
    read_cookies,
    read_users,
    repo_root_path,
    users_file_path,
)


def test_repo_root_path_contains_config_dir():
    assert (repo_root_path() / "config").is_dir()


def test_config_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TIKTOK_RECORDER_CONFIG_DIR", str(tmp_path))
    assert config_dir() == tmp_path


def test_ensure_config_file_bootstraps_from_example(monkeypatch, tmp_path):
    monkeypatch.setenv("TIKTOK_RECORDER_CONFIG_DIR", str(tmp_path))
    example = tmp_path / "cookies.json.example"
    example.write_text(
        json.dumps(
            {
                "sessionid": "",
                "sessionid_ss": "",
                "tt-target-idc": "",
            }
        ),
        encoding="utf-8",
    )

    path = _ensure_config_file("cookies.json")

    assert path == tmp_path / "cookies.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(
        example.read_text(encoding="utf-8")
    )


def test_ensure_config_file_does_not_overwrite_existing(monkeypatch, tmp_path):
    monkeypatch.setenv("TIKTOK_RECORDER_CONFIG_DIR", str(tmp_path))
    example = tmp_path / "users.json.example"
    example.write_text('{"users": []}', encoding="utf-8")
    real = tmp_path / "users.json"
    real.write_text('{"users": ["creator"]}', encoding="utf-8")

    path = _ensure_config_file("users.json")

    assert path == real
    assert json.loads(path.read_text(encoding="utf-8")) == {"users": ["creator"]}


def test_cookies_file_path_bootstraps_and_read_cookies_loads(monkeypatch, tmp_path):
    monkeypatch.setenv("TIKTOK_RECORDER_CONFIG_DIR", str(tmp_path))
    example = tmp_path / "cookies.json.example"
    example.write_text(
        json.dumps({"sessionid": "abc", "sessionid_ss": "", "tt-target-idc": ""}),
        encoding="utf-8",
    )

    path = cookies_file_path()
    cookies = read_cookies()

    assert path == str(tmp_path / "cookies.json")
    assert cookies["sessionid"] == "abc"


def test_read_users_from_bootstrapped_file(monkeypatch, tmp_path):
    monkeypatch.setenv("TIKTOK_RECORDER_CONFIG_DIR", str(tmp_path))
    example = tmp_path / "users.json.example"
    example.write_text('{"users": ["alpha", "beta"]}', encoding="utf-8")

    users_path = users_file_path()
    users = read_users()

    assert users_path == str(tmp_path / "users.json")
    assert users == ["alpha", "beta"]
