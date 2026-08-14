import html
import json
import re
import threading
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from tiktok_live_recorder.http_utils.http_client import HttpClient
from tiktok_live_recorder.utils.enums import StatusCode, TikTokError
from tiktok_live_recorder.utils.logger_manager import logger
from tiktok_live_recorder.utils.utils import (
    has_session_cookie,
    cookie_key_summary,
    _cookie_value,
)
from tiktok_live_recorder.utils.custom_exceptions import (
    UserLiveError,
    TikTokRecorderError,
    LiveNotFound,
    TikRecUnavailableError,
)

DEFAULT_API_TIMEOUT = (10, 20)


@dataclass(frozen=True)
class UserRoomInfo:
    """Room lookup plus stable TikTok identity fields when available."""

    room_id: str | None = None
    unique_id: str | None = None
    sec_uid: str | None = None


_STREAM_URL_PATTERN = re.compile(
    r"https?://[^\s\"'<>\\]+\.(?:flv|m3u8)[^\s\"'<>\\]*", re.IGNORECASE
)


def _looks_like_stream_url(value: str) -> bool:
    return bool(value and _STREAM_URL_PATTERN.fullmatch(value.rstrip("\\")))


def collect_stream_urls_from_obj(obj) -> list[str]:
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "stream_data" and isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                        for url in collect_video_stream_urls_from_sdk_data(parsed):
                            _append_stream_url(found, url)
                    except json.JSONDecodeError:
                        pass
                    continue
                if key in ("streamData", "hevcStreamData") and isinstance(value, str):
                    try:
                        walk(json.loads(value))
                    except json.JSONDecodeError:
                        pass
                    continue
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            _append_stream_url(found, node)

    walk(obj)
    return order_stream_urls(found)


_VIDEO_SDK_KEY_ORDER = ("uhd", "hd", "or4", "sd", "ld", "zsd")
_FLV_QUALITY_MARKERS = ("_or4", "_hd", "_sd", "_ld", "_zsd", "_uhd")
_ONLY_AUDIO_QUERY = re.compile(r"(?:^|&)only_audio=(?:1|true)(?:&|$)", re.IGNORECASE)


def is_audio_only_stream_url(url: str) -> bool:
    if not url:
        return False
    lower = url.lower()
    if "_ao.flv" in lower or "_ao/" in lower:
        return True
    for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True):
        if key.lower() == "only_audio" and value.lower() in ("1", "true"):
            return True
    return "only_audio=1" in lower or "only_audio=true" in lower


def origin_url_from_audio_only(url: str) -> str | None:
    """Return the origin FLV URL by stripping only_audio from an ao pull URL."""
    if not url:
        return None
    lower = url.lower()
    if "_ao.flv" in lower or "_ao/" in lower:
        return None

    parts = urlsplit(url)
    kept: list[tuple[str, str]] = []
    saw_only_audio = False
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() == "only_audio" and value.lower() in ("1", "true"):
            saw_only_audio = True
            continue
        kept.append((key, value))
    if not saw_only_audio and not _ONLY_AUDIO_QUERY.search(parts.query):
        return None

    derived = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )
    derived = html.unescape(derived.rstrip("\\"))
    if not derived or is_audio_only_stream_url(derived):
        return None
    return derived


def video_stream_url_from_candidate(url: str | None) -> str | None:
    """Keep a video pull URL, or derive origin video from an audio-only FLV."""
    if not url:
        return None
    normalized = html.unescape(url.rstrip("\\"))
    if is_audio_only_stream_url(normalized):
        normalized = origin_url_from_audio_only(normalized) or ""
    if not normalized or not _looks_like_stream_url(normalized):
        return None
    if is_audio_only_stream_url(normalized):
        return None
    return normalized


def is_unmarked_origin_flv_url(url: str) -> bool:
    """True for FLV URLs with no quality suffix (_hd, _or4, …) in the path."""
    if not url or is_audio_only_stream_url(url):
        return False
    path = urlsplit(url).path.lower()
    if ".flv" not in path:
        return False
    return not any(marker in path for marker in _FLV_QUALITY_MARKERS)


def _append_stream_url(found: list[str], url: str | None) -> None:
    candidate = video_stream_url_from_candidate(url)
    if candidate and candidate not in found:
        found.append(candidate)


def collect_video_stream_urls_from_sdk_data(sdk_root: dict) -> list[str]:
    sdk_data = (
        sdk_root.get("data") if isinstance(sdk_root.get("data"), dict) else sdk_root
    )
    if not isinstance(sdk_data, dict):
        return []

    found: list[str] = []
    ordered_keys = sorted(
        sdk_data.keys(),
        key=lambda key: (
            _VIDEO_SDK_KEY_ORDER.index(key) if key in _VIDEO_SDK_KEY_ORDER else 99
        ),
    )
    for sdk_key in ordered_keys:
        entry = sdk_data.get(sdk_key)
        if not isinstance(entry, dict):
            continue
        for branch in ("main", "backup"):
            stream = entry.get(branch) or {}
            if isinstance(stream, dict):
                for url_key in ("flv", "hls", "m3u8"):
                    _append_stream_url(found, stream.get(url_key))
    return found


def order_stream_urls(urls: list[str]) -> list[str]:
    if not urls:
        return []

    expanded: list[str] = []
    for url in urls:
        candidate = video_stream_url_from_candidate(url)
        if candidate:
            expanded.append(candidate)
        elif url and not is_audio_only_stream_url(url):
            expanded.append(url)

    video_urls = [url for url in expanded if not is_audio_only_stream_url(url)]
    pool = video_urls or expanded

    def priority(url: str) -> tuple[int, int]:
        lower = url.lower()
        if is_audio_only_stream_url(url):
            return (999, 0)
        if ".flv" not in lower:
            return (200, 0)
        path = urlsplit(url).path.lower()
        for idx, marker in enumerate(_FLV_QUALITY_MARKERS):
            if marker in path:
                return (idx + 1, 0)
        return (0, 0)

    seen: set[str] = set()
    ordered: list[str] = []
    for url in sorted(pool, key=priority):
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def pick_preferred_stream_url(urls: list[str]) -> str | None:
    ordered = order_stream_urls(urls)
    if ordered:
        return ordered[0]
    return None


def extract_embedded_json_from_page(content: str) -> list[dict]:
    blobs: list[dict] = []

    sigi_match = re.search(
        r'<script[^>]+id=["\']SIGI_STATE["\'][^>]*>(.*?)</script>',
        content,
        re.DOTALL,
    )
    if sigi_match:
        try:
            blobs.append(json.loads(sigi_match.group(1)))
        except json.JSONDecodeError:
            pass

    universal_match = re.search(
        r'<script[^>]+id=["\']__UNIVERSAL_DATA_FOR_REHYDRATION__["\'][^>]*>(.*?)</script>',
        content,
        re.DOTALL,
    )
    if universal_match:
        try:
            blobs.append(json.loads(universal_match.group(1)))
        except json.JSONDecodeError:
            pass

    return blobs


def _normalize_username(user: str) -> str:
    return user.lower().lstrip("@")


def _identity_from_user_obj(user_obj: dict | None) -> tuple[str | None, str | None]:
    """Return (unique_id, sec_uid) from a TikTok user-like dict."""
    if not isinstance(user_obj, dict):
        return None, None

    nested = user_obj.get("user")
    if isinstance(nested, dict):
        user_obj = nested

    unique_id = None
    for key in ("uniqueId", "unique_id", "display_id", "displayId"):
        value = user_obj.get(key)
        if value:
            unique_id = str(value).lstrip("@").strip()
            break

    sec_uid = None
    for key in ("secUid", "sec_uid"):
        value = user_obj.get(key)
        if value:
            sec_uid = str(value).strip()
            break

    return unique_id or None, sec_uid or None


def parse_user_room_info_from_payload(data: dict | None) -> UserRoomInfo:
    """Extract roomId / uniqueId / secUid from tikrec or Euler-style JSON."""
    if not isinstance(data, dict):
        return UserRoomInfo()

    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        return UserRoomInfo()

    user = payload.get("user")
    room_info = payload.get("room_info")
    if not isinstance(room_info, dict):
        room_info = {}

    room_id = None
    if isinstance(user, dict):
        for key in ("roomId", "room_id"):
            value = user.get(key)
            if value is not None and str(value).strip():
                room_id = str(value)
                break
    if room_id is None:
        for key in ("id", "roomId", "room_id"):
            value = room_info.get(key)
            if value is not None and str(value).strip():
                room_id = str(value)
                break

    unique_id, sec_uid = _identity_from_user_obj(
        user if isinstance(user, dict) else None
    )
    if unique_id is None or sec_uid is None:
        owner = (
            room_info.get("owner") or room_info.get("anchor") or payload.get("owner")
        )
        alt_unique, alt_sec = _identity_from_user_obj(
            owner if isinstance(owner, dict) else None
        )
        unique_id = unique_id or alt_unique
        sec_uid = sec_uid or alt_sec

    return UserRoomInfo(room_id=room_id, unique_id=unique_id, sec_uid=sec_uid)


def extract_user_identity_from_obj(obj) -> dict | None:
    """
    Find uniqueId + secUid from embedded profile/live page JSON.
    Prefers webapp.user-detail.userInfo.user when present.
    """
    preferred: dict | None = None
    fallback: dict | None = None

    def consider(node: dict) -> None:
        nonlocal preferred, fallback
        user_info = node.get("userInfo")
        if isinstance(user_info, dict) and isinstance(user_info.get("user"), dict):
            unique_id, sec_uid = _identity_from_user_obj(user_info.get("user"))
            if unique_id and sec_uid:
                preferred = preferred or {"uniqueId": unique_id, "secUid": sec_uid}
                return

        unique_id, sec_uid = _identity_from_user_obj(node)
        if not unique_id or not sec_uid:
            return
        if ("secUid" in node or "sec_uid" in node) and (
            "uniqueId" in node or "unique_id" in node
        ):
            fallback = fallback or {"uniqueId": unique_id, "secUid": sec_uid}

    def walk(node):
        if isinstance(node, dict):
            consider(node)
            if preferred:
                return
            for value in node.values():
                walk(value)
                if preferred:
                    return
        elif isinstance(node, list):
            for value in node:
                walk(value)
                if preferred:
                    return

    if isinstance(obj, dict):
        scope = obj.get("__DEFAULT_SCOPE__")
        if isinstance(scope, dict):
            detail = scope.get("webapp.user-detail")
            if isinstance(detail, dict):
                user_info = detail.get("userInfo")
                if isinstance(user_info, dict):
                    unique_id, sec_uid = _identity_from_user_obj(user_info.get("user"))
                    if unique_id and sec_uid:
                        return {"uniqueId": unique_id, "secUid": sec_uid}
        walk(obj)

    return preferred or fallback


def extract_user_identity_from_page(content: str) -> dict | None:
    for blob in extract_embedded_json_from_page(content):
        identity = extract_user_identity_from_obj(blob)
        if identity:
            return identity
    return None


def _owner_unique_id(owner) -> str | None:
    if not isinstance(owner, dict):
        return None

    user_obj = owner.get("user")
    if isinstance(user_obj, dict):
        owner = user_obj

    for key in ("uniqueId", "unique_id", "display_id", "displayId"):
        value = owner.get(key)
        if value:
            return str(value)
    return None


def _room_id_from_node(node: dict) -> str | None:
    for key in ("roomId", "room_id", "id"):
        value = node.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _room_status(node: dict) -> int | None:
    for key in ("status", "room_status", "liveStatus"):
        value = node.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _is_room_node_for_user(node: dict, user: str) -> bool:
    user_key = _normalize_username(user)

    unique_id = _owner_unique_id(node)
    if unique_id and _normalize_username(unique_id) == user_key:
        return True

    for owner_key in ("owner", "user", "host"):
        owner = node.get(owner_key)
        unique_id = _owner_unique_id(owner)
        if unique_id and _normalize_username(unique_id) == user_key:
            return True

    live_room_user = node.get("liveRoomUserInfo")
    if isinstance(live_room_user, dict):
        unique_id = _owner_unique_id(live_room_user)
        if unique_id and _normalize_username(unique_id) == user_key:
            return True

    return False


def _node_looks_like_live_room(node: dict) -> bool:
    if _room_status(node) is not None:
        return True
    if _room_id_from_node(node) is not None:
        return True
    for key in ("stream_url", "streamUrl", "streamData", "hevcStreamData"):
        if key in node:
            return True
    return False


def _extract_live_room_user_info_context(
    obj: dict, user: str, room_id: str | None = None
) -> dict | None:
    """
    Parse TikTok's LiveRoom.liveRoomUserInfo layout (common on WAF-restricted lives).
    """
    live_room = obj.get("LiveRoom") if "LiveRoom" in obj else None
    if live_room is None and "liveRoomUserInfo" in obj:
        live_room = {"liveRoomUserInfo": obj.get("liveRoomUserInfo")}
    if not isinstance(live_room, dict):
        return None

    live_room_user = live_room.get("liveRoomUserInfo")
    if not isinstance(live_room_user, dict):
        return None

    user_obj = live_room_user.get("user") or {}
    if not isinstance(user_obj, dict):
        return None

    unique_id = user_obj.get("uniqueId") or user_obj.get("unique_id")
    if not unique_id or _normalize_username(unique_id) != _normalize_username(user):
        return None

    room_obj = live_room_user.get("liveRoom") or {}
    user_status = _room_status(user_obj)
    room_status = _room_status(room_obj) if isinstance(room_obj, dict) else None
    if user_status != 2 and room_status != 2:
        return None

    node_room_id = _room_id_from_node(user_obj)
    if room_id and node_room_id and str(node_room_id) != str(room_id):
        return None

    stream_urls = order_stream_urls(collect_stream_urls_from_obj(live_room_user))
    if not stream_urls:
        return None

    return {
        "stream_urls": stream_urls,
        "room_id": node_room_id,
        "status": 2,
    }


def extract_user_live_context_from_obj(
    obj, user: str, room_id: str | None = None
) -> dict | None:
    """
    Return stream URLs only when embedded JSON confirms @user is live (status 2).
    Ignores recommended/suggested streams for other creators on the same page.
    """
    live_room_context = _extract_live_room_user_info_context(obj, user, room_id=room_id)
    if live_room_context:
        return live_room_context

    best: dict | None = None

    def consider(node: dict) -> None:
        nonlocal best
        if not _is_room_node_for_user(node, user) or not _node_looks_like_live_room(
            node
        ):
            return

        status = _room_status(node)
        if status is not None and status != 2:
            return

        node_room_id = _room_id_from_node(node)
        if room_id and node_room_id and str(node_room_id) != str(room_id):
            return

        stream_urls = collect_stream_urls_from_obj(node)
        if not stream_urls:
            return

        candidate = {
            "stream_urls": stream_urls,
            "room_id": node_room_id,
            "status": status,
        }
        if best is None:
            best = candidate
            return

        if status == 2 and best.get("status") != 2:
            best = candidate
            return

        if (
            room_id
            and node_room_id == str(room_id)
            and best.get("room_id") != str(room_id)
        ):
            best = candidate

    def walk(node):
        if isinstance(node, dict):
            consider(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(obj)
    return best


def extract_user_live_context_from_page(
    content: str, user: str, room_id: str | None = None
) -> dict | None:
    best: dict | None = None

    for blob in extract_embedded_json_from_page(content):
        context = extract_user_live_context_from_obj(blob, user, room_id=room_id)
        if context is None:
            continue
        if best is None or (context.get("status") == 2 and best.get("status") != 2):
            best = context

    return best


def parse_unique_id_from_tikwm_posts(data: dict | None) -> str | None:
    """Extract author.unique_id from a TikWM /api/user/posts JSON body."""
    if not isinstance(data, dict):
        return None
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        return None
    videos = payload.get("videos")
    if not isinstance(videos, list) or not videos:
        return None
    first = videos[0]
    if not isinstance(first, dict):
        return None
    author = first.get("author")
    if not isinstance(author, dict):
        return None
    unique_id = author.get("unique_id") or author.get("uniqueId")
    if unique_id and str(unique_id).strip():
        return str(unique_id).lstrip("@").strip()
    return None


def _looks_like_cf_challenge(text: str, status_code: int | None = None) -> bool:
    if status_code == 403:
        return True
    if not text:
        return False
    lower = text.lower()
    return any(
        marker in lower
        for marker in ("just a moment", "cf-challenge", "challenge-platform")
    )


class TikTokAPI:
    def __init__(self, proxy, cookies):
        self.BASE_URL = "https://www.tiktok.com"
        self.WEBCAST_URL = "https://webcast.tiktok.com"
        self.API_URL = "https://www.tiktok.com/api-live/user/room/"
        self.EULER_API = "https://tiktok.eulerstream.com"
        self.TIKREC_API = "https://tikrec.com"
        self.TIKWM_API = "https://www.tikwm.com"
        self._cookies = cookies
        self._http_lock = threading.Lock()
        self._tikrec_warned_this_cycle = False
        self._tikwm_warned = False

        self.http_client = HttpClient(proxy, cookies).req
        self._http_client_stream = HttpClient(proxy, cookies).req_stream
        self._stream_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.6478.127 Safari/537.36"
            ),
            "Referer": "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com",
        }

    def _private_account_error(self) -> TikTokError:
        if not has_session_cookie(self._cookies):
            return TikTokError.ACCOUNT_PRIVATE
        try:
            if not self._is_authenticated():
                return TikTokError.ACCOUNT_PRIVATE_SESSION_EXPIRED
        except Exception:
            pass
        return TikTokError.ACCOUNT_PRIVATE_COOKIES_PRESENT

    def _live_restriction_error(self) -> TikTokError:
        if not has_session_cookie(self._cookies):
            return TikTokError.LIVE_RESTRICTION
        try:
            if not self._is_authenticated():
                return TikTokError.LIVE_RESTRICTION_SESSION_EXPIRED
        except Exception:
            pass
        return TikTokError.LIVE_RESTRICTION_COOKIES_PRESENT

    def _is_authenticated(self) -> bool:
        response = self.http_client.get(f"{self.BASE_URL}/foryou")
        response.raise_for_status()

        content = response.text
        return "login-title" not in content

    def is_country_blacklisted(self) -> bool:
        """
        Checks if the user is in a blacklisted country that requires login
        """
        response = self.http_client.get(f"{self.BASE_URL}/live", allow_redirects=False)

        return response.status_code == StatusCode.REDIRECT

    def _api_get(self, url: str, **kwargs):
        kwargs.setdefault("timeout", DEFAULT_API_TIMEOUT)
        return self.http_client.get(url, **kwargs)

    def check_alive(
        self,
        room_id: str,
        *,
        assume_live_on_error: bool = False,
    ) -> bool:
        """Lightweight live check — check_alive API only (no room/info or page scrape)."""
        if not room_id:
            return False

        try:
            with self._http_lock:
                alive_data = self._api_get(
                    f"{self.WEBCAST_URL}/webcast/room/check_alive/"
                    f"?aid=1988&region=CH&room_ids={room_id}&user_is_login=true"
                ).json()
        except requests.RequestException as ex:
            if assume_live_on_error:
                logger.debug(
                    f"check_alive network error for room {room_id} ({ex}); "
                    "assuming still live"
                )
                return True
            logger.warning(f"check_alive network error for room {room_id}: {ex}")
            return False

        data_list = alive_data.get("data")
        return (
            isinstance(data_list, list)
            and bool(data_list)
            and isinstance(data_list[0], dict)
            and bool(data_list[0].get("alive", False))
        )

    def is_room_alive(self, room_id: str, user: str | None = None) -> bool:
        """
        Checking whether the user is live.
        """
        if not room_id:
            raise UserLiveError(TikTokError.USER_NOT_CURRENTLY_LIVE)

        if not self.check_alive(room_id):
            return False

        room_info = self._api_get(
            f"{self.WEBCAST_URL}/webcast/room/info/?aid=1988&room_id={room_id}"
        ).json()

        status_code = room_info.get("status_code", 0)
        if status_code == 4003110:
            if not user:
                return False
            return bool(self._get_stream_url_from_page(user, room_id=room_id))

        if status_code != 0:
            return False

        room_data = room_info.get("data") or {}
        room_status = room_data.get("status")
        if room_status is not None and str(room_status) != "2":
            return False

        stream_url = room_data.get("stream_url") or {}
        sdk_stream_data = (
            (stream_url.get("live_core_sdk_data") or {})
            .get("pull_data", {})
            .get("stream_data")
        )

        return bool(
            sdk_stream_data
            or stream_url.get("flv_pull_url")
            or stream_url.get("hls_pull_url")
            or stream_url.get("hls_pull_url_map")
            or stream_url.get("rtmp_pull_url")
        )

    def get_sec_uid(self):
        """
        Returns the sec_uid of the authenticated user.
        """
        response = self.http_client.get(f"{self.BASE_URL}/foryou")

        sec_uid = re.search('"secUid":"(.*?)",', response.text)
        if sec_uid:
            sec_uid = sec_uid.group(1)

        return sec_uid

    def get_user_from_room_id(self, room_id) -> str:
        """
        Given a room_id, I get the username
        """
        data = self.http_client.get(
            f"{self.WEBCAST_URL}/webcast/room/info/?aid=1988&room_id={room_id}"
        ).json()

        if "Follow the creator to watch their LIVE" in json.dumps(data):
            raise UserLiveError(TikTokError.ACCOUNT_PRIVATE_FOLLOW)

        if "This account is private" in data:
            raise UserLiveError(self._private_account_error())

        display_id = data.get("data", {}).get("owner", {}).get("display_id")
        if display_id is None:
            raise TikTokRecorderError(TikTokError.USERNAME_ERROR)

        return display_id

    def get_room_and_user_from_url(self, live_url: str):
        """
        Given a url, get user and room_id.
        """
        response = self.http_client.get(live_url, allow_redirects=False)
        content = response.text

        if response.status_code == StatusCode.REDIRECT:
            raise UserLiveError(TikTokError.COUNTRY_BLACKLISTED)

        if response.status_code == StatusCode.MOVED:  # MOBILE URL
            matches = re.findall("com/@(.*?)/live", content)
            if len(matches) < 1:
                raise LiveNotFound(TikTokError.INVALID_TIKTOK_LIVE_URL)

            user = matches[0]

        # https://www.tiktok.com/@<username>/live
        match = re.match(r"https?://(?:www\.)?tiktok\.com/@([^/]+)/live", live_url)
        if match:
            user = match.group(1)

        room_id = self.get_room_id_from_user(user)

        return user, room_id

    def reset_tikrec_warn_flag(self) -> None:
        """Allow one tikrec-unavailable warning per watchlist poll cycle."""
        self._tikrec_warned_this_cycle = False

    def _log_tikrec_unavailable(self, error: TikRecUnavailableError) -> None:
        if self._tikrec_warned_this_cycle:
            return
        self._tikrec_warned_this_cycle = True
        logger.warning(
            f"[!] tikrec is unavailable ({error}). "
            "Falling back to unsigned API — recording continues but may be less reliable."
        )

    def _old_get_user_room_info(self, user: str) -> UserRoomInfo:
        params = {"uniqueId": user, "giftInfo": "false"}

        response = self._api_get(
            f"{self.EULER_API}/webcast/room_info",
            params=params,
            headers={"x-api-key": ""},
        )

        if response.status_code != 200:
            raise UserLiveError(TikTokError.ROOM_ID_ERROR)

        return parse_user_room_info_from_payload(response.json())

    def _old_get_room_id_from_user(self, user: str) -> str | None:
        return self._old_get_user_room_info(user).room_id

    def _tikrec_get_room_id_signed_url(self, user: str) -> str:
        try:
            response = self._api_get(
                f"{self.TIKREC_API}/tiktok/room/api/sign",
                params={"unique_id": user},
            )
            response.raise_for_status()
        except Exception as e:
            raise TikRecUnavailableError(
                f"tikrec signing service is unreachable: {e}"
            ) from e

        try:
            data = response.json()
        except ValueError as e:
            raise TikRecUnavailableError(
                "tikrec signing service returned an invalid response "
                "(expected JSON, got something else — the service may be down)."
            ) from e

        signed_path = data.get("signed_path")
        if not signed_path:
            raise TikRecUnavailableError(
                "tikrec signing service did not return a signed_path "
                "(the service may be down or overloaded)."
            )

        return f"{self.BASE_URL}{signed_path}"

    def get_user_room_info(self, user: str) -> UserRoomInfo:
        """Given a username, get room_id and identity fields when available."""
        try:
            signed_url = self._tikrec_get_room_id_signed_url(user)
        except TikRecUnavailableError as e:
            self._log_tikrec_unavailable(e)
            return self._old_get_user_room_info(user)

        try:
            response = self._api_get(signed_url)
        except requests.RequestException:
            return self._old_get_user_room_info(user)

        content = response.text

        if not content or "Please wait" in content:
            raise UserLiveError(TikTokError.WAF_BLOCKED)

        return parse_user_room_info_from_payload(response.json())

    def get_room_id_from_user(self, user: str) -> str | None:
        """Given a username, get the room_id."""
        return self.get_user_room_info(user).room_id

    def get_user_identity_from_profile(self, user: str) -> dict | None:
        """
        Scrape tiktok.com/@user for uniqueId + secUid.
        Useful when a renamed handle still redirects, or room APIs omit identity.
        """
        handle = user.lstrip("@").strip()
        if not handle:
            return None
        try:
            response = self.http_client.get(f"{self.BASE_URL}/@{handle}")
            return extract_user_identity_from_page(response.text)
        except Exception as e:
            logger.debug(f"Failed to extract identity from @{handle} profile: {e}")
            return None

    def _log_tikwm_unavailable(self, reason: str) -> None:
        if self._tikwm_warned:
            return
        self._tikwm_warned = True
        logger.warning(
            f"[!] TikWM secUid resolver unavailable ({reason}). "
            "Falling back to stored handle — identity tracking continues without "
            "secUid→uniqueId refresh until the next successful lookup."
        )

    def resolve_unique_id_from_sec_uid(self, sec_uid: str) -> str | None:
        """
        Resolve the current TikTok uniqueId for a stable secUid via TikWM.

        Uses the same HttpClient (UA / proxy / curl_cffi) as other API calls.
        Soft-fails on Cloudflare or network errors (returns None).
        """
        sec = (sec_uid or "").strip()
        if not sec:
            return None

        param_tries = [("sec_uid", sec), ("unique_id", sec)]
        last_reason = "no response"
        for param_name, param_value in param_tries:
            try:
                response = self._api_get(
                    f"{self.TIKWM_API}/api/user/posts",
                    params={param_name: param_value, "count": "1", "cursor": "0"},
                    headers={
                        "Referer": f"{self.TIKWM_API}/",
                        "Accept": "application/json, text/plain, */*",
                    },
                )
            except requests.RequestException as e:
                last_reason = str(e)
                continue

            text = response.text or ""
            if _looks_like_cf_challenge(text, response.status_code):
                self._log_tikwm_unavailable("Cloudflare challenge")
                return None
            if response.status_code != 200:
                last_reason = f"HTTP {response.status_code}"
                continue

            try:
                data = response.json()
            except ValueError:
                last_reason = "invalid JSON"
                continue

            unique_id = parse_unique_id_from_tikwm_posts(data)
            if unique_id:
                return unique_id
            last_reason = (
                f"code={data.get('code')!r} msg={data.get('msg')!r}"
                if isinstance(data, dict)
                else "empty videos"
            )

        logger.debug(f"TikWM secUid resolve failed: {last_reason}")
        return None

    def get_followers_list(self, sec_uid) -> list:
        """
        Returns all followers for the authenticated user by paginating
        """
        followers = []
        cursor = 0
        has_more = True

        ms_token = self.http_client.get(
            f"{self.BASE_URL}/api/user/list/?"
            "WebIdLastTime=1747672102&aid=1988&app_language=it-IT&app_name=tiktok_web&"
            "browser_language=it-IT&browser_name=Mozilla&browser_online=true&"
            "browser_platform=Linux%20x86_64&"
            "browser_version=5.0%20%28X11%3B%20Linux%20x86_64%29%20AppleWebKit%2F537.36%20%28KHTML%2C%20like%20Gecko%29%20Chrome%2F140.0.0.0%20Safari%2F537.36&"
            "channel=tiktok_web&cookie_enabled=true&count=5&data_collection_enabled=true&"
            "device_id=7506194516308166166&device_platform=web_pc&focus_state=true&"
            "from_page=user&history_len=3&is_fullscreen=false&is_page_visible=true&"
            "maxCursor=0&minCursor=0&odinId=7246312836442604570&os=linux&priority_region=IT&"
            "referer=&region=IT&root_referer=https%3A%2F%2Fwww.tiktok.com%2Flive&scene=21&"
            "screen_height=1080&screen_width=1920&tz_name=Europe%2FRome&user_is_login=true&"
            "verifyFp=verify_mh4yf0uq_rdjp1Xwt_OoTk_4Jrf_AS8H_sp31opbnJFre&webcast_language=it-IT&"
            "msToken=GphHoLvRR4QxA5AWVwDkrs3AbumoK5H8toE8LVHtj6cce3ToGdXhMfvDWzOXG-0GXUWoaGVHrwGNA4k_NnjuFFnHgv2S5eMjsvtkAhwMPa13xLmvP7tumx0KreFjPwTNnOj-BvAkPdO5Zrev3hoFBD9lHVo=&X-Bogus=&X-Gnarly="
        ).cookies["msToken"]

        while has_more:
            url = (
                "https://www.tiktok.com/api/user/list/?"
                "WebIdLastTime=1747672102&aid=1988&app_language=it-IT&app_name=tiktok_web"
                "&browser_language=it-IT&browser_name=Mozilla&browser_online=true"
                "&browser_platform=Linux%20x86_64&browser_version=5.0%20%28X11%3B%20Linux%20x86_64%29%20AppleWebKit%2F537.36%20%28KHTML%2C%20like%20Gecko%29%20Chrome%2F140.0.0.0%20Safari%2F537.36&channel=tiktok_web&"
                "cookie_enabled=true&count=5&data_collection_enabled=true&device_id=7506194516308166166"
                "&device_platform=web_pc&focus_state=true&from_page=user&history_len=3&"
                f"is_fullscreen=false&is_page_visible=true&maxCursor={cursor}&minCursor={cursor}&"
                "odinId=7246312836442604570&os=linux&priority_region=IT&referer=&"
                "region=IT&scene=21&screen_height=1080&screen_width=1920"
                "&tz_name=Europe%2FRome&user_is_login=true&"
                f"secUid={sec_uid}&verifyFp=verify_mh4yf0uq_rdjp1Xwt_OoTk_4Jrf_AS8H_sp31opbnJFre&"
                f"webcast_language=it-IT&msToken={ms_token}&X-Bogus=&X-Gnarly="
            )

            response = self.http_client.get(url)

            if response.status_code != StatusCode.OK:
                raise TikTokRecorderError("Failed to retrieve followers list.")

            if not response.content:
                raise TikTokRecorderError("Empty response from TikTok followers API.")

            data = response.json()
            user_list = data.get("userList", [])

            for user in user_list:
                username = user.get("user", {}).get("uniqueId")
                if username:
                    followers.append(username)

            has_more = data.get("hasMore", False)
            new_cursor = data.get("minCursor", 0)

            if new_cursor == cursor:
                break

            cursor = new_cursor

        if not followers:
            raise TikTokRecorderError("Followers list is empty.")

        return followers

    def _log_waf_cookie_status(self) -> None:
        cookies = self._cookies or {}
        logger.debug(f"WAF cookies: {cookie_key_summary(cookies)}")
        if _cookie_value(cookies, "sessionid_ss") and not _cookie_value(
            cookies, "sessionid"
        ):
            logger.warning(
                "Only sessionid_ss is set. Add sessionid from browser cookies to improve "
                "WAF and restricted-live access."
            )

    def _get_stream_urls_from_page(
        self, user: str, room_id: str | None = None
    ) -> list[str]:
        """
        Fetch the live page HTML and extract stream URLs for @user when they are live.
        Used when the webcast API returns status code 4003110 (WAF/access restriction).
        """
        try:
            live_page_url = f"{self.BASE_URL}/@{user}/live/"
            response = self.http_client.get(live_page_url)
            content = response.text

            context = extract_user_live_context_from_page(
                content, user, room_id=room_id
            )
            if context:
                return context["stream_urls"]

            return []
        except Exception as e:
            logger.warning(f"Failed to extract stream URL from page: {e}")
            return []

    def _get_stream_url_from_page(
        self, user: str, room_id: str | None = None
    ) -> str | None:
        urls = self._get_stream_urls_from_page(user, room_id=room_id)
        chosen = pick_preferred_stream_url(urls)
        if chosen:
            logger.debug(f"Found stream URL from page: {chosen[:80]}...")
        return chosen

    def _add_live_url_candidate(self, candidates: list[str], url: str | None) -> None:
        candidate = video_stream_url_from_candidate(url)
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    def get_live_urls(self, room_id: str, user: str = None) -> list[str]:
        """
        Return candidate CDN URLs (flv or m3u8) for the streaming.
        If the API returns status code 4003110 and a username is provided,
        falls back to scraping the live page directly.
        """
        data = self.http_client.get(
            f"{self.WEBCAST_URL}/webcast/room/info/?aid=1988&room_id={room_id}"
        ).json()

        if "This account is private" in data:
            raise UserLiveError(self._private_account_error())

        status_code = data.get("status_code", 0)

        if status_code == 4003110:
            self._log_waf_cookie_status()
            if user:
                logger.debug(
                    f"API blocked by WAF (4003110). Trying page scrape for @{user}..."
                )
                fallback_urls = self._get_stream_urls_from_page(user, room_id=room_id)
                if fallback_urls:
                    return order_stream_urls(fallback_urls)
                logger.warning(
                    f"Live page scrape for @{user} returned no FLV or HLS URLs."
                )
            else:
                logger.warning(
                    "API blocked by WAF (4003110) and no username available for page scrape fallback."
                )

            raise UserLiveError(self._live_restriction_error())

        room_data = data.get("data") or {}
        room_status = room_data.get("status")
        if room_status is not None and str(room_status) != "2":
            raise UserLiveError(TikTokError.USER_NOT_CURRENTLY_LIVE)

        stream_url = room_data.get("stream_url", {})

        sdk_data_str = (
            stream_url.get("live_core_sdk_data", {})
            .get("pull_data", {})
            .get("stream_data")
        )
        candidates = []
        if not sdk_data_str:
            logger.warning(
                "No SDK stream data found. Falling back to legacy URLs. Consider contacting the developer to update the code."
            )
            flv_pull_url = stream_url.get("flv_pull_url", {})
            for key in ("FULL_HD1", "HD1", "SD2", "SD1"):
                self._add_live_url_candidate(candidates, flv_pull_url.get(key))
            self._add_live_url_candidate(candidates, stream_url.get("hls_pull_url"))
            self._add_live_url_candidate(candidates, stream_url.get("rtmp_pull_url"))
            return order_stream_urls(candidates)

        # Extract stream options
        sdk_data = json.loads(sdk_data_str).get("data", {})
        qualities = (
            stream_url.get("live_core_sdk_data", {})
            .get("pull_data", {})
            .get("options", {})
            .get("qualities", [])
        )
        if not qualities:
            logger.warning("No qualities found in the stream data. Returning None.")
            return candidates
        level_map = {q["sdk_key"]: q["level"] for q in qualities}

        ordered_sdk_keys = sorted(
            sdk_data.keys(), key=lambda key: level_map.get(key, -1), reverse=True
        )
        for sdk_key in ordered_sdk_keys:
            entry = sdk_data[sdk_key]
            stream_main = entry.get("main", {})
            self._add_live_url_candidate(candidates, stream_main.get("flv"))
            self._add_live_url_candidate(
                candidates, stream_main.get("hls") or stream_main.get("m3u8")
            )

        flv_pull_url = stream_url.get("flv_pull_url", {})
        for key in ("FULL_HD1", "HD1", "SD2", "SD1"):
            self._add_live_url_candidate(candidates, flv_pull_url.get(key))
        self._add_live_url_candidate(candidates, stream_url.get("hls_pull_url"))
        self._add_live_url_candidate(candidates, stream_url.get("rtmp_pull_url"))

        return order_stream_urls(candidates)

    def get_live_url(self, room_id: str, user: str = None) -> str | None:
        """Return the first candidate CDN URL for the streaming."""
        live_urls = self.get_live_urls(room_id, user=user)
        if live_urls:
            return live_urls[0]
        return None

    def get_live_url_candidates(self, room_id: str, user: str = None) -> list[str]:
        """Return candidate CDN URLs for the streaming."""
        return self.get_live_urls(room_id, user=user)

    def download_live_stream(self, live_url: str):
        """
        Generator that yields live stream bytes.

        Uses a fresh requests Session per call so concurrent recording threads
        do not share cookies/TLS state (which causes SSL errors and hung reads).
        Read timeout forces reconnect/alive-check instead of hanging forever after
        a live ends without closing the socket.
        """
        session = requests.Session()
        session.headers.update(self._stream_headers)
        if self._cookies:
            session.cookies.update(self._cookies)

        try:
            with session.get(
                live_url,
                stream=True,
                timeout=(10, 45),
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
        finally:
            session.close()
