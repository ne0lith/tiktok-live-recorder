import shutil

import pytest

from tiktok_live_recorder.utils.utils import (
    default_output_base,
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
