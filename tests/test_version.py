import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.version import get_version  # noqa: E402


def test_get_version_reads_pyproject():
    assert get_version() == "7.7.1"
