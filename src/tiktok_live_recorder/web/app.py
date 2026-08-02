from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tiktok_live_recorder.utils.custom_exceptions import UserLiveError
from tiktok_live_recorder.utils.enums import Mode
from tiktok_live_recorder.utils.version import get_version
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
from tiktok_live_recorder.utils.logger_manager import clear_log_file, get_log_file_path
from tiktok_live_recorder.web.logs import read_log_tail
from tiktok_live_recorder.web.media import (
    find_orphan_flv_files,
    is_active_recording_file,
    resolve_media_path,
    scan_media_library,
)
from tiktok_live_recorder.web.thumbnails import (
    delete_thumbnail,
    ensure_thumbnail,
)

if TYPE_CHECKING:
    from tiktok_live_recorder.core.tiktok_recorder import TikTokRecorder
    from tiktok_live_recorder.utils.recorder_config import RecorderConfig

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


class UsernamePayload(BaseModel):
    username: str = Field(min_length=1)


class RuntimeSettingsPayload(BaseModel):
    automatic_interval_minutes: int | None = Field(default=None, ge=1)
    use_telegram: bool | None = None
    max_concurrent_converts: int | None = Field(default=None, ge=1)


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


def _scan_media(recorder: TikTokRecorder, output_base: Path, custom_output) -> dict:
    return scan_media_library(
        output_base,
        custom_output,
        recorder.active_recording_output_paths(),
    )


def _delete_media_file(
    output_base: Path,
    custom_output: str | Path | None,
    username: str,
    filename: str,
    *,
    subdir: str | None = None,
    active_output_paths: set[str] | None = None,
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
    if path.name.endswith("_flv.mp4") and is_active_recording_file(
        path, active_output_paths
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot delete an in-progress recording",
        )
    path.unlink()
    delete_thumbnail(path)


def create_app(recorder: TikTokRecorder, config: RecorderConfig) -> FastAPI:
    output_base = default_output_base()
    custom_output = config.output

    app = FastAPI(title="TikTok Live Recorder", docs_url=None, redoc_url=None)

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def dashboard_index() -> HTMLResponse:
        version = get_version()
        ffmpeg_json = json.dumps(recorder.get_ffmpeg_info())
        html = (
            INDEX_HTML.read_text(encoding="utf-8")
            .replace("__VERSION__", version)
            .replace("__FFMPEG_JSON__", ffmpeg_json)
        )
        return HTMLResponse(
            html,
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return recorder.get_status()

    @app.get("/api/version")
    def api_version() -> dict[str, str]:
        return {"version": get_version()}

    @app.get("/api/media")
    def api_media() -> dict[str, list[dict]]:
        return _scan_media(recorder, output_base, custom_output)

    @app.get("/api/media/leftover-flv")
    def api_leftover_flv() -> dict[str, Any]:
        pending = find_orphan_flv_files(
            output_base,
            custom_output,
            recorder.active_recording_output_paths(),
        )
        return {
            "count": len(pending),
            "files": pending,
        }

    @app.post("/api/media/move-leftover-flv")
    def api_move_leftover_flv() -> dict[str, Any]:
        return recorder.move_leftover_flvs()

    def _queue_media_repair(
        username: str,
        filename: str,
        *,
        subdir: str | None = None,
    ) -> dict[str, Any]:
        path = resolve_media_path(
            output_base,
            custom_output,
            username,
            filename,
            subdir=subdir,
        )
        if path is None:
            raise HTTPException(status_code=404, detail="Media not found")
        if path.name.endswith("_flv.mp4") and is_active_recording_file(
            path, recorder.active_recording_output_paths()
        ):
            raise HTTPException(
                status_code=400,
                detail="Cannot repair an in-progress recording",
            )
        try:
            return recorder.enqueue_media_repair(username, str(path))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/media/{username}/{filename}/repair")
    def api_repair_media(username: str, filename: str) -> dict[str, Any]:
        return _queue_media_repair(username, filename)

    @app.post("/api/media/{username}/legacy/{filename}/repair")
    def api_repair_legacy_media(username: str, filename: str) -> dict[str, Any]:
        return _queue_media_repair(username, filename, subdir="legacy")

    @app.get("/api/ffmpeg")
    def api_ffmpeg() -> dict[str, Any]:
        return recorder.get_ffmpeg_info()

    @app.get("/api/events")
    async def api_events(request: Request):
        async def event_stream():
            media_tick = 0
            while True:
                if await request.is_disconnected():
                    break
                status = recorder.get_status()
                yield f"data: {json.dumps({'type': 'status', 'data': status})}\n\n"
                media_tick += 1
                if media_tick >= 30:
                    media_tick = 0
                    media = _scan_media(recorder, output_base, custom_output)
                    yield f"data: {json.dumps({'type': 'media', 'data': media})}\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

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

    @app.post("/api/logs/clear")
    def api_clear_logs() -> dict[str, Any]:
        try:
            return clear_log_file()
        except OSError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Could not clear log file (it may be locked): {exc}",
            ) from exc

    @app.get("/media/{username}/{filename}/thumb")
    def serve_media_thumb(username: str, filename: str):
        path = resolve_media_path(output_base, custom_output, username, filename)
        if path is None:
            raise HTTPException(status_code=404, detail="Media not found")
        thumb_path = ensure_thumbnail(path, ffmpeg_path=config.ffmpeg_path)
        if thumb_path is None:
            raise HTTPException(status_code=404, detail="Thumbnail not available")
        return FileResponse(
            thumb_path,
            media_type="image/jpeg",
            filename=thumb_path.name,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.get("/media/{username}/legacy/{filename}/thumb")
    def serve_legacy_media_thumb(username: str, filename: str):
        path = resolve_media_path(
            output_base,
            custom_output,
            username,
            filename,
            subdir="legacy",
        )
        if path is None:
            raise HTTPException(status_code=404, detail="Media not found")
        thumb_path = ensure_thumbnail(path, ffmpeg_path=config.ffmpeg_path)
        if thumb_path is None:
            raise HTTPException(status_code=404, detail="Thumbnail not available")
        return FileResponse(
            thumb_path,
            media_type="image/jpeg",
            filename=thumb_path.name,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

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
        _delete_media_file(
            output_base,
            custom_output,
            username,
            filename,
            active_output_paths=recorder.active_recording_output_paths(),
        )

    @app.delete("/api/media/{username}/legacy/{filename}", status_code=204)
    def delete_legacy_media(username: str, filename: str):
        _delete_media_file(
            output_base,
            custom_output,
            username,
            filename,
            subdir="legacy",
            active_output_paths=recorder.active_recording_output_paths(),
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
        recorder.poll_user_now(username)
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

    @app.post("/api/users/{username}/poll")
    def poll_user(username: str) -> dict[str, str]:
        if recorder.mode not in (Mode.WATCHLIST,):
            raise HTTPException(
                status_code=400,
                detail="Per-user poll is only supported in watchlist mode",
            )
        username = _normalize_username(username)
        if not username:
            raise HTTPException(status_code=400, detail="Username is required")
        recorder.poll_user_now(username)
        return {"status": "poll_requested", "username": username}

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
            "max_concurrent_converts": recorder.max_concurrent_converts,
            "ffmpeg": recorder.get_ffmpeg_info(),
        }

    @app.put("/api/settings/runtime")
    def put_runtime_settings(payload: RuntimeSettingsPayload) -> dict[str, Any]:
        try:
            settings = recorder.update_runtime_settings(
                automatic_interval_minutes=payload.automatic_interval_minutes,
                use_telegram=payload.use_telegram,
                max_concurrent_converts=payload.max_concurrent_converts,
            )
        except ValueError as ex:
            raise HTTPException(status_code=400, detail=str(ex)) from ex
        config.automatic_interval = settings["automatic_interval_minutes"]
        config.use_telegram = settings["use_telegram"]
        config.max_concurrent_converts = settings["max_concurrent_converts"]
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

    @app.middleware("http")
    async def dashboard_static_cache_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/js/") or path.endswith(".css"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app
