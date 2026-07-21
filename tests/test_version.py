import sys
import tomllib
from pathlib import Path

import pytest

from tiktok_live_recorder.utils.args_handler import parse_args
from tiktok_live_recorder.utils.version import get_version

ROOT = Path(__file__).resolve().parents[1]


def test_get_version_reads_pyproject():
    with (ROOT / "pyproject.toml").open("rb") as f:
        expected = tomllib.load(f)["project"]["version"]
    assert get_version() == expected


def test_version_flag_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["tiktok-live-recorder", "--version"])
    with pytest.raises(SystemExit) as exc_info:
        parse_args()
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert get_version() in captured.out
