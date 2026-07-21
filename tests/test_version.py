import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.version import get_version  # noqa: E402
from utils.args_handler import parse_args  # noqa: E402

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
