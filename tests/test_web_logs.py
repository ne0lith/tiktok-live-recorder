from fastapi.testclient import TestClient

from tiktok_live_recorder.utils.enums import Mode
from tiktok_live_recorder.utils.recorder_config import RecorderConfig
from tiktok_live_recorder.web.app import create_app
from tiktok_live_recorder.web.logs import read_log_tail


def test_read_log_tail_returns_last_lines(tmp_path):
    log_file = tmp_path / "tiktok-recorder.log"
    log_file.write_text(
        "\n".join(f"2026-07-26 10:00:{i:02d} [INFO] line {i}" for i in range(10)),
        encoding="utf-8",
    )

    payload = read_log_tail(log_file, max_lines=3)

    assert payload["lines"] == [
        "2026-07-26 10:00:07 [INFO] line 7",
        "2026-07-26 10:00:08 [INFO] line 8",
        "2026-07-26 10:00:09 [INFO] line 9",
    ]
    assert payload["truncated"] is True


def test_read_log_tail_filters_by_level_and_keeps_traceback_context(tmp_path):
    log_file = tmp_path / "tiktok-recorder.log"
    log_file.write_text(
        "\n".join(
            [
                "2026-07-26 10:00:00 [INFO] healthy",
                "2026-07-26 10:00:01 [ERROR] boom",
                "Traceback (most recent call last):",
                '  File "app.py", line 1, in <module>',
                "2026-07-26 10:00:02 [WARNING] hiccup",
            ]
        ),
        encoding="utf-8",
    )

    payload = read_log_tail(log_file, max_lines=50, min_level="ERROR")

    assert payload["lines"] == [
        "2026-07-26 10:00:01 [ERROR] boom",
        "Traceback (most recent call last):",
        '  File "app.py", line 1, in <module>',
    ]


def test_read_log_tail_missing_file(tmp_path):
    payload = read_log_tail(tmp_path / "missing.log")

    assert payload["lines"] == []
    assert payload["size"] == 0


def test_api_logs_endpoint(tmp_path, monkeypatch):
    from tests.test_web_dashboard import StubRecorder

    log_file = tmp_path / "tiktok-recorder.log"
    log_file.write_text("2026-07-26 10:00:00 [INFO] hello\n", encoding="utf-8")
    recorder = StubRecorder()
    config = RecorderConfig(mode=Mode.WATCHLIST, users=["alpha"], cookies={})
    monkeypatch.setattr(
        "tiktok_live_recorder.web.app.get_log_file_path",
        lambda: log_file,
    )
    client = TestClient(create_app(recorder, config))

    response = client.get("/api/logs?lines=10")

    assert response.status_code == 200
    assert response.json()["lines"] == ["2026-07-26 10:00:00 [INFO] hello"]

    bad = client.get("/api/logs?lines=0")
    assert bad.status_code == 400

    bad_level = client.get("/api/logs?level=NOPE")
    assert bad_level.status_code == 400
