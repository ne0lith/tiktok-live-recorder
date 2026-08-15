from dataclasses import dataclass

from tiktok_live_recorder.utils.enums import Mode


@dataclass
class RecorderConfig:
    mode: Mode
    url: str | None = None
    user: str | None = None
    users: list[str] | None = None
    room_id: str | None = None
    automatic_interval: int = 5
    max_concurrent_converts: int = 1
    cookies: dict | None = None
    proxy: str | None = None
    output: str | None = None
    duration: int | None = None
    use_telegram: bool = False
    # Experimental: follow handle renames via secUid. Not guaranteed to be developed further.
    use_identity_tracking: bool = False
    auto_update_when_idle: bool = False
    bitrate: str | None = None
    ffmpeg_path: str | None = None
    users_file: str | None = None
    web_host: str = "0.0.0.0"
    web_port: int = 8787
    no_web: bool = False
