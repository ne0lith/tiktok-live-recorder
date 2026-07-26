from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tiktok_live_recorder.utils.custom_exceptions import UserLiveError
from tiktok_live_recorder.utils.enums import Mode
from tiktok_live_recorder.utils.utils import (
    add_user_to_file,
    cookies_file_path,
    default_output_base,
    read_cookies,
    read_paused_users,
    read_telegram_config,
    remove_user_from_file,
    telegram_file_path,
    users_file_path,
    write_cookies,
    write_paused_users,
    write_telegram_config,
)
from tiktok_live_recorder.utils.logger_manager import get_log_file_path
from tiktok_live_recorder.web.logs import read_log_tail
from tiktok_live_recorder.web.media import resolve_media_path, scan_media_library

if TYPE_CHECKING:
    from tiktok_live_recorder.core.tiktok_recorder import TikTokRecorder
    from tiktok_live_recorder.utils.recorder_config import RecorderConfig

STATIC_DIR = Path(__file__).resolve().parent / "static"


class UsernamePayload(BaseModel):
    username: str = Field(min_length=1)


class RuntimeSettingsPayload(BaseModel):
    automatic_interval_minutes: int | None = Field(default=None, ge=1)
    use_telegram: bool | None = None


class RecordPayload(BaseModel):
    username: str | None = None
    room_id: str | None = None


def _normalize_username(username: str) -> str:
    return username.lstrip("@").strip()


def _ensure_users_file(recorder: TikTokRecorder) -> str:
    if recorder.users_file:
        return recorder.users_file
    path = users_file_path()
    recorder.users_file = path
    return path


def _delete_media_file(
    output_base: Path,
    custom_output: str | Path | None,
    username: str,
    filename: str,
    *,
    subdir: str | None = None,
) -> None:
    path = resolve_media_path(
        output_base,
        custom_output,
        username,
        filename,
        subdir=subdir,
    )
    if path is None:
        raise HTTPException(status_code=404, detail="Media not found")
    if path.name.endswith("_flv.mp4"):
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an in-progress recording",
        )
    path.unlink()


def create_app(recorder: TikTokRecorder, config: RecorderConfig) -> FastAPI:
    output_base = default_output_base()
    custom_output = config.output

    app = FastAPI(title="TikTok Live Recorder", docs_url=None, redoc_url=None)

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return recorder.get_status()

    @app.get("/api/media")
    def api_media() -> dict[str, list[dict]]:
        return scan_media_library(output_base, custom_output)

    @app.get("/api/logs")
    def api_logs(lines: int = 300, level: str | None = None) -> dict[str, Any]:
        if lines < 1 or lines > 2000:
            raise HTTPException(
                status_code=400,
                detail="lines must be between 1 and 2000",
            )
        if level is not None:
            level = level.upper()
            try:
                payload = read_log_tail(
                    get_log_file_path(),
                    max_lines=lines,
                    min_level=level,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return payload
        return read_log_tail(get_log_file_path(), max_lines=lines)

    @app.get("/media/{username}/{filename}")
    def serve_media(username: str, filename: str):
        path = resolve_media_path(output_base, custom_output, username, filename)
        if path is None:
            raise HTTPException(status_code=404, detail="Media not found")
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=filename,
        )

    @app.get("/media/{username}/legacy/{filename}")
    def serve_legacy_media(username: str, filename: str):
        path = resolve_media_path(
            output_base,
            custom_output,
            username,
            filename,
            subdir="legacy",
        )
        if path is None:
            raise HTTPException(status_code=404, detail="Media not found")
        return FileResponse(
            path,
            media_type="video/mp4",
            filename=filename,
        )

    @app.delete("/api/media/{username}/{filename}", status_code=204)
    def delete_media(username: str, filename: str):
        _delete_media_file(output_base, custom_output, username, filename)

    @app.delete("/api/media/{username}/legacy/{filename}", status_code=204)
    def delete_legacy_media(username: str, filename: str):
        _delete_media_file(
            output_base,
            custom_output,
            username,
            filename,
            subdir="legacy",
        )

    @app.post("/api/users")
    def add_user(payload: UsernamePayload) -> dict[str, Any]:
        if recorder.mode not in (Mode.WATCHLIST,):
            raise HTTPException(
                status_code=400,
                detail="Adding users is only supported in watchlist mode",
            )
        username = _normalize_username(payload.username)
        if not username:
            raise HTTPException(status_code=400, detail="Username is required")

        users_path = _ensure_users_file(recorder)
        users = add_user_to_file(users_path, username)
        recorder.users = users
        recorder.force_poll()
        return {"users": users}

    @app.delete("/api/users/{username}")
    def delete_user(username: str) -> dict[str, Any]:
        if recorder.mode not in (Mode.WATCHLIST,):
            raise HTTPException(
                status_code=400,
                detail="Removing users is only supported in watchlist mode",
            )
        username = _normalize_username(username)
        users_path = _ensure_users_file(recorder)
        users = remove_user_from_file(users_path, username)

        paused = read_paused_users()
        if username.lower() in paused:
            paused = {u for u in paused if u != username.lower()}
            write_paused_users(paused)

        recorder.users = users
        recorder.force_poll()
        return {"users": users}

    @app.post("/api/users/{username}/pause")
    def pause_user(username: str) -> dict[str, Any]:
        username = _normalize_username(username)
        paused = read_paused_users()
        paused.add(username.lower())
        write_paused_users(paused)
        recorder.force_poll()
        return {"paused": sorted(paused)}

    @app.post("/api/users/{username}/resume")
    def resume_user(username: str) -> dict[str, Any]:
        username = _normalize_username(username)
        paused = {u for u in read_paused_users() if u != username.lower()}
        write_paused_users(paused)
        recorder.force_poll()
        return {"paused": sorted(paused)}

    @app.post("/api/poll")
    def force_poll() -> dict[str, str]:
        recorder.force_poll()
        return {"status": "poll_requested"}

    @app.post("/api/recordings/{username}/stop")
    def stop_recording(username: str) -> dict[str, Any]:
        username = _normalize_username(username)
        if not recorder.stop_user(username):
            raise HTTPException(status_code=404, detail="No active recording for user")
        return {"status": "stopping", "username": username}

    @app.post("/api/record")
    def start_record(payload: RecordPayload) -> dict[str, Any]:
        username = _normalize_username(payload.username) if payload.username else None
        room_id = payload.room_id.strip() if payload.room_id else None
        if not username and not room_id:
            raise HTTPException(
                status_code=400,
                detail="username or room_id is required",
            )
        try:
            return recorder.start_recording_now(username=username, room_id=room_id)
        except UserLiveError as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex
        except RuntimeError as ex:
            raise HTTPException(status_code=409, detail=str(ex)) from ex
        except ValueError as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex

    @app.get("/api/settings/runtime")
    def get_runtime_settings() -> dict[str, Any]:
        return {
            "automatic_interval_minutes": recorder.automatic_interval,
            "use_telegram": recorder.use_telegram,
        }

    @app.put("/api/settings/runtime")
    def put_runtime_settings(payload: RuntimeSettingsPayload) -> dict[str, Any]:
        try:
            settings = recorder.update_runtime_settings(
                automatic_interval_minutes=payload.automatic_interval_minutes,
                use_telegram=payload.use_telegram,
            )
        except ValueError as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex
        config.automatic_interval = settings["automatic_interval_minutes"]
        config.use_telegram = settings["use_telegram"]
        return settings

    @app.get("/api/settings/cookies")
    def get_cookies() -> dict[str, Any]:
        cookies = read_cookies()
        return {"path": cookies_file_path(), "cookies": cookies}

    @app.put("/api/settings/cookies")
    def put_cookies(payload: dict[str, Any]) -> dict[str, Any]:
        cookies = payload.get("cookies", payload)
        if not isinstance(cookies, dict):
            raise HTTPException(status_code=400, detail="Expected a cookies object")
        write_cookies(cookies)
        recorder.reload_cookies()
        return {"path": cookies_file_path(), "cookies": cookies}

    @app.get("/api/settings/telegram")
    def get_telegram() -> dict[str, Any]:
        try:
            config_data = read_telegram_config()
        except FileNotFoundError:
            config_data = {}
        except OSError:
            config_data = {}
        return {"path": telegram_file_path(), "telegram": config_data}

    @app.put("/api/settings/telegram")
    def put_telegram(payload: dict[str, Any]) -> dict[str, Any]:
        telegram = payload.get("telegram", payload)
        if not isinstance(telegram, dict):
            raise HTTPException(status_code=400, detail="Expected a telegram object")
        write_telegram_config(telegram)
        return {"path": telegram_file_path(), "telegram": telegram}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
