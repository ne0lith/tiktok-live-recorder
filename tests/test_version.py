import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.version import get_version  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_get_version_reads_pyproject():
    with (ROOT / "pyproject.toml").open("rb") as f:
        expected = tomllib.load(f)["project"]["version"]
    assert get_version() == expected
