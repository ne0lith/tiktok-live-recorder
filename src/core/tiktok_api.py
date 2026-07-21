import html
import json
import re
import threading

import requests

from http_utils.http_client import HttpClient
from utils.enums import StatusCode, TikTokError
from utils.logger_manager import logger
from utils.utils import has_session_cookie, cookie_key_summary, _cookie_value
from utils.custom_exceptions import (
    UserLiveError,
    TikTokRecorderError,
    LiveNotFound,
    TikRecUnavailableError,
)


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


def is_audio_only_stream_url(url: str) -> bool:
    lower = url.lower()
    if "only_audio=1" in lower or "only_audio=true" in lower:
        return True
    if "_ao.flv" in lower or "_ao/" in lower:
        return True
    return False


def _append_stream_url(found: list[str], url: str | None) -> None:
    if not url or not _looks_like_stream_url(url):
        return
    if is_audio_only_stream_url(url):
        return
    normalized = html.unescape(url.rstrip("\\"))
    if normalized not in found:
        found.append(normalized)


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
        if sdk_key == "ao":
            continue
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

    video_urls = [url for url in urls if not is_audio_only_stream_url(url)]
    pool = video_urls or urls

    def priority(url: str) -> tuple[int, int]:
        lower = url.lower()
        if is_audio_only_stream_url(url):
            return (999, 0)
        if ".flv" not in lower:
            return (200, 0)
        for idx, marker in enumerate(_FLV_QUALITY_MARKERS):
            if marker in lower:
                return (idx, 0)
        return (100, 0)

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


class TikTokAPI:
    def __init__(self, proxy, cookies):
        self.BASE_URL = "https://www.tiktok.com"
        self.WEBCAST_URL = "https://webcast.tiktok.com"
        self.API_URL = "https://www.tiktok.com/api-live/user/room/"
        self.EULER_API = "https://tiktok.eulerstream.com"
        self.TIKREC_API = "https://tikrec.com"
        self._cookies = cookies
        self._http_lock = threading.Lock()

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

    def check_alive(self, room_id: str) -> bool:
        """Lightweight live check — check_alive API only (no room/info or page scrape)."""
        if not room_id:
            return False

        with self._http_lock:
            alive_data = self.http_client.get(
                f"{self.WEBCAST_URL}/webcast/room/check_alive/"
                f"?aid=1988&region=CH&room_ids={room_id}&user_is_login=true"
            ).json()

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

        room_info = self.http_client.get(
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

    def _old_get_room_id_from_user(self, user: str) -> str:
        params = {"uniqueId": user, "giftInfo": "false"}

        response = self.http_client.get(
            f"{self.EULER_API}/webcast/room_info",
            params=params,
            headers={"x-api-key": ""},
        )

        if response.status_code != 200:
            raise UserLiveError(TikTokError.ROOM_ID_ERROR)

        data = response.json()

        room_id = data.get("data", {}).get("room_info", {}).get("id")
        if not room_id:
            raise UserLiveError(TikTokError.ROOM_ID_ERROR)

        return room_id

    def _tikrec_get_room_id_signed_url(self, user: str) -> str:
        try:
            response = self.http_client.get(
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

    def get_room_id_from_user(self, user: str) -> str | None:
        """Given a username, get the room_id."""
        try:
            signed_url = self._tikrec_get_room_id_signed_url(user)
        except TikRecUnavailableError as e:
            logger.warning(
                f"[!] tikrec is unavailable ({e}). "
                "Falling back to unsigned API — recording continues but may be less reliable."
            )
            return self._old_get_room_id_from_user(user)

        response = self.http_client.get(signed_url)
        content = response.text

        if not content or "Please wait" in content:
            raise UserLiveError(TikTokError.WAF_BLOCKED)

        data = response.json()
        return (data.get("data") or {}).get("user", {}).get("roomId")

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
        if url and url not in candidates:
            candidates.append(url)

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
