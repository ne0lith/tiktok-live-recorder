from tiktok_live_recorder.updater import (
    classify_changed_files,
    compare_versions,
    is_updatable_install,
)


def test_compare_versions_ordering():
    assert compare_versions("8.20.1", "8.20.2") < 0
    assert compare_versions("8.21.0", "8.20.2") > 0
    assert compare_versions("8.20.1", "8.20.1") == 0


def test_classify_hot_static_only():
    paths = [
        "src/tiktok_live_recorder/web/static/js/update.js",
        "src/tiktok_live_recorder/web/static/index.html",
        "pyproject.toml",
        "uv.lock",
        "CHANGELOG.md",
    ]
    assert classify_changed_files(paths) == "hot"


def test_classify_hot_pyproject_and_lock_only():
    assert classify_changed_files(["pyproject.toml", "uv.lock"]) == "hot"


def test_classify_restart_backend_python():
    paths = [
        "src/tiktok_live_recorder/web/static/js/update.js",
        "src/tiktok_live_recorder/web/app.py",
    ]
    assert classify_changed_files(paths) == "restart"


def test_classify_restart_core_python():
    paths = ["src/tiktok_live_recorder/core/tiktok_recorder.py"]
    assert classify_changed_files(paths) == "restart"


def test_is_updatable_install_requires_git_and_writable(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (repo / ".git").mkdir()

    monkeypatch.setattr(
        "tiktok_live_recorder.updater._command_available",
        lambda name: name in {"git", "uv"},
    )
    assert is_updatable_install(repo) is True

    read_only = tmp_path / "readonly"
    read_only.mkdir()
    (read_only / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (read_only / ".git").mkdir()
    monkeypatch.setattr("os.access", lambda *_args, **_kwargs: False)
    assert is_updatable_install(read_only) is False


def test_apply_hot_update_runs_uv_sync_when_lock_changes(tmp_path, monkeypatch):
    from tiktok_live_recorder.updater import apply_hot_update

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "1.0.0"\n', encoding="utf-8"
    )
    (repo / ".git").mkdir()

    monkeypatch.setattr(
        "tiktok_live_recorder.updater.is_updatable_install", lambda _root=None: True
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.updater.git_pull",
        lambda _root: ["uv.lock", "pyproject.toml"],
    )
    synced = {"called": False}
    monkeypatch.setattr(
        "tiktok_live_recorder.updater.uv_sync",
        lambda _root: synced.__setitem__("called", True),
    )

    result = apply_hot_update(repo)
    assert synced["called"] is True
    assert result.scope == "hot"
    assert result.synced_dependencies is True


def test_apply_hot_update_static_reload_flag(tmp_path, monkeypatch):
    from tiktok_live_recorder.updater import apply_hot_update

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    monkeypatch.setattr(
        "tiktok_live_recorder.updater.is_updatable_install", lambda _root=None: True
    )
    monkeypatch.setattr(
        "tiktok_live_recorder.updater.git_pull",
        lambda _root: ["src/tiktok_live_recorder/web/static/js/update.js"],
    )

    result = apply_hot_update(repo)
    assert result.static_changed is True
    assert result.synced_dependencies is False
