from enum import Enum, IntEnum


class Regex(Enum):
    def __str__(self):
        return str(self.value)

    IS_TIKTOK_LIVE = r".*www\.tiktok\.com.*|.*vm\.tiktok\.com.*"


class TimeOut(IntEnum):
    """
    Enumeration that defines timeout values.
    """

    def __mul__(self, operator):
        return self.value * operator

    ONE_MINUTE = 60
    AUTOMATIC_MODE = 5
    CONNECTION_CLOSED = 2


class StatusCode(IntEnum):
    OK = 200
    REDIRECT = 302
    MOVED = 301


class Mode(IntEnum):
    """
    Enumeration that represents the recording modes.
    """

    MANUAL = 0
    AUTOMATIC = 1
    FOLLOWERS = 2
    WATCHLIST = 3


class Error(Enum):
    """
    Enumeration that contains possible errors while using TikTok-Live-Recorder.
    """

    def __str__(self):
        return str(self.value)

    CONNECTION_CLOSED = "Connection broken by the server."
    CONNECTION_CLOSED_AUTOMATIC = f"{CONNECTION_CLOSED}. Try again after delay of {TimeOut.CONNECTION_CLOSED} minutes"


class TikTokError(Enum):
    """
    Enumeration that contains possible errors of TikTok
    """

    def __str__(self):
        return str(self.value)

    COUNTRY_BLACKLISTED = (
        "Captcha required or country blocked. "
        "Use a VPN, room_id, or authenticate with cookies.\n"
        "How to set cookies: https://github.com/ne0lith/tiktok-live-recorder/blob/main/docs/GUIDE.md#how-to-set-cookies\n"
        "How to get room_id: https://github.com/ne0lith/tiktok-live-recorder/blob/main/docs/GUIDE.md#how-to-get-room_id\n"
    )

    COUNTRY_BLACKLISTED_AUTO_MODE = (
        "Automatic mode is available only in unblocked countries. "
        "Use a VPN or authenticate with cookies.\n"
        "How to set cookies: https://github.com/ne0lith/tiktok-live-recorder/blob/main/docs/GUIDE.md#how-to-set-cookies\n"
    )

    COUNTRY_BLACKLISTED_FOLLOWERS_MODE = (
        "Followers mode is available only in unblocked countries. "
        "Use a VPN or authenticate with cookies.\n"
        "How to set cookies: https://github.com/ne0lith/tiktok-live-recorder/blob/main/docs/GUIDE.md#how-to-set-cookies\n"
    )

    COOKIES_GUIDE_URL = "https://github.com/ne0lith/tiktok-live-recorder/blob/main/docs/GUIDE.md#how-to-set-cookies"

    ACCOUNT_PRIVATE = (
        "Account is private, login required. "
        "Please add your sessionid_ss cookie to config/cookies.json. "
        f"How to set cookies: {COOKIES_GUIDE_URL}"
    )

    ACCOUNT_PRIVATE_COOKIES_PRESENT = (
        "Account is private. config/cookies.json was loaded but access was denied. "
        "Your session may be expired — refresh sessionid_ss in config/cookies.json, "
        "or ensure you follow this account."
    )

    ACCOUNT_PRIVATE_SESSION_EXPIRED = (
        "Account is private. config/cookies.json was loaded but your TikTok session "
        "appears expired. Refresh sessionid_ss in config/cookies.json. "
        f"How to set cookies: {COOKIES_GUIDE_URL}"
    )

    ACCOUNT_PRIVATE_FOLLOW = (
        "This account is private. Follow the creator to access their LIVE."
    )

    LIVE_RESTRICTION = (
        "Live is restricted or private, login required. "
        "Please add your sessionid_ss cookie to config/cookies.json. "
        f"How to set cookies: {COOKIES_GUIDE_URL}"
    )

    LIVE_RESTRICTION_COOKIES_PRESENT = (
        "Live access blocked by WAF or restriction. config/cookies.json was loaded "
        "but no stream URL could be retrieved from the live page. "
        "Your session may be expired — refresh sessionid_ss in config/cookies.json, "
        "or try a VPN/proxy."
    )

    LIVE_RESTRICTION_SESSION_EXPIRED = (
        "Live access blocked. config/cookies.json was loaded but your TikTok session "
        "appears expired. Refresh sessionid_ss in config/cookies.json. "
        f"How to set cookies: {COOKIES_GUIDE_URL}"
    )

    USERNAME_ERROR = "Username / RoomID not found or the user has never been in live."

    ROOM_ID_ERROR = "Error extracting RoomID"

    USER_NEVER_BEEN_LIVE = "The user has never hosted a live stream on TikTok."

    USER_NOT_CURRENTLY_LIVE = "The user is not hosting a live stream at the moment."

    RETRIEVE_LIVE_URL = "Unable to retrieve live streaming url. Please try again later."

    INVALID_TIKTOK_LIVE_URL = "The provided URL is not a valid TikTok live stream."

    WAF_BLOCKED = "Your IP is blocked by TikTok WAF. Please change your IP address."


class Info(Enum):
    """
    Release notes shown when an update is available.
    """

    def __str__(self):
        return str(self.value)

    def __iter__(self):
        return iter(self.value)

    NEW_FEATURES = [
        "Rejected ended TikTok rooms that still expose stale stream URLs.",
        "Tried alternate stream URLs and skipped empty CDN responses.",
        "Resolved room IDs before country checks for manual username recordings.",
        "Validated live rooms with stream info to avoid fake recordings.",
        "Added restricted LIVE fallback for TikTok 4003110 responses.",
        "Added -ffmpeg-path for custom FFmpeg binaries.",
    ]
