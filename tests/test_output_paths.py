import shutil

import pytest

from tiktok_live_recorder.utils.utils import (
    default_output_base,
    default_to_fix_dir,
    output_dir_for_user,
    repo_root_path,
)


@pytest.fixture
def creator_output_dir():
    """Use the real output base, then remove the test subdir afterward."""
    out_dir = default_output_base() / "creator"
    yield out_dir
    if out_dir.is_dir():
        shutil.rmtree(out_dir)


def test_default_output_base_is_repo_output():
    assert default_output_base() == repo_root_path() / "output"


def test_default_to_fix_dir_is_repo_to_fix():
    assert default_to_fix_dir() == repo_root_path() / "to_fix"


def test_unique_to_fix_dest_adds_numeric_suffix(tmp_path):
    from tiktok_live_recorder.web.media import unique_to_fix_dest

    dest_dir = tmp_path / "to_fix"
    first = unique_to_fix_dest(dest_dir, "TK_alpha_2026.01.01_12-00-00_flv.mp4")
    assert first == dest_dir / "TK_alpha_2026.01.01_12-00-00_flv.mp4"
    first.write_bytes(b"one")
    second = unique_to_fix_dest(dest_dir, "TK_alpha_2026.01.01_12-00-00_flv.mp4")
    assert second == dest_dir / "TK_alpha_2026.01.01_12-00-00_flv.1.mp4"


def test_output_dir_for_user_uses_username_subfolder_when_base_omitted(
    creator_output_dir,
):
    out_dir = output_dir_for_user(None, "creator")
    assert out_dir == default_output_base() / "creator"
    assert out_dir == creator_output_dir
    assert out_dir.is_dir()


def test_output_dir_for_user_uses_exact_dir_when_base_provided(tmp_path):
    out_dir = output_dir_for_user(tmp_path, "creator")
    assert out_dir == tmp_path
    assert out_dir.is_dir()


def test_output_dir_for_user_strips_at_sign_only_for_default_layout(creator_output_dir):
    default_dir = output_dir_for_user(None, "@creator")
    assert default_dir == default_output_base() / "creator"
    assert default_dir == creator_output_dir
