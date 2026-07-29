import pytest
from unittest.mock import MagicMock, patch

import requests

from tiktok_live_recorder.core.tiktok_api import TikTokAPI
from tiktok_live_recorder.utils.custom_exceptions import (
    TikRecUnavailableError,
    UserLiveError,
)


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = responses
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return FakeResponse(self.responses.pop(0))


def build_api(*responses):
    api = TikTokAPI.__new__(TikTokAPI)
    api.WEBCAST_URL = "https://webcast.tiktok.com"
    api.http_client = FakeHttpClient(list(responses))
    api._http_lock = __import__("threading").Lock()
    api._cookies = {}
    api._stream_headers = {}
    return api


def test_is_room_alive_rejects_fake_check_alive_positive():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {"data": {"message": "Request params error"}, "status_code": 10011},
    )

    assert api.is_room_alive("123") is False


def test_is_room_alive_accepts_confirmed_stream_room():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {
            "data": {
                "status": 2,
                "stream_url": {
                    "live_core_sdk_data": {"pull_data": {"stream_data": '{"data": {}}'}}
                },
            },
            "status_code": 0,
        },
    )

    assert api.is_room_alive("123") is True


def test_is_room_alive_rejects_waf_without_user():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {"data": {}, "status_code": 4003110},
    )

    assert api.is_room_alive("123") is False


def test_is_room_alive_confirms_waf_live_via_page_scrape():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {"data": {}, "status_code": 4003110},
    )
    api._get_stream_url_from_page = lambda user, room_id=None: "https://cdn/example.flv"

    assert api.is_room_alive("123", user="creator") is True


def test_is_room_alive_rejects_waf_when_page_has_no_stream():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {"data": {}, "status_code": 4003110},
    )
    api._get_stream_url_from_page = lambda user, room_id=None: None

    assert api.is_room_alive("123", user="creator") is False


def test_is_room_alive_skips_room_info_when_check_alive_is_false():
    api = build_api({"data": [{"alive": False, "room_id": 123}], "status_code": 0})

    assert api.is_room_alive("123") is False
    assert len(api.http_client.urls) == 1


def test_check_alive_is_lightweight():
    api = build_api({"data": [{"alive": True, "room_id": 123}], "status_code": 0})

    assert api.check_alive("123") is True
    assert len(api.http_client.urls) == 1
    assert "check_alive" in api.http_client.urls[0]


def test_check_alive_assumes_live_on_network_error_when_requested():
    api = build_api({"data": [{"alive": True, "room_id": 123}], "status_code": 0})
    api.http_client.get = lambda url, **kwargs: (_ for _ in ()).throw(
        __import__("requests").ConnectionError("dns down")
    )

    assert api.check_alive("123", assume_live_on_error=True) is True
    assert api.check_alive("123") is False


def test_is_room_alive_rejects_null_check_alive_data():
    api = build_api({"data": None, "status_code": 0})

    assert api.is_room_alive("123") is False
    assert len(api.http_client.urls) == 1


def test_is_room_alive_rejects_null_room_info_data():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {"data": None, "status_code": 0},
    )

    assert api.is_room_alive("123") is False


def test_is_room_alive_rejects_ended_room_with_stale_stream_urls():
    api = build_api(
        {"data": [{"alive": True, "room_id": 123}], "status_code": 0},
        {
            "data": {
                "status": 4,
                "finish_time": 1784118433,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {"stream_data": '{"data": {}}'}
                    },
                    "flv_pull_url": {"HD1": "https://example.com/stale.flv"},
                },
            },
            "status_code": 0,
        },
    )

    assert api.is_room_alive("123") is False


def test_get_live_url_rejects_ended_room_with_stale_stream_urls():
    api = build_api(
        {
            "data": {
                "status": 4,
                "finish_time": 1784118433,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {"stream_data": '{"data": {}}'}
                    },
                    "flv_pull_url": {"HD1": "https://example.com/stale.flv"},
                },
            },
            "status_code": 0,
        },
    )

    with pytest.raises(UserLiveError, match="not hosting a live stream"):
        api.get_live_url("123", user="creator")


def test_get_live_url_candidates_returns_ordered_unique_streams():
    api = build_api(
        {
            "data": {
                "status": 2,
                "stream_url": {
                    "live_core_sdk_data": {
                        "pull_data": {
                            "stream_data": (
                                '{"data": {'
                                '"hd": {"main": {"flv": "https://cdn/hd.flv"}},'
                                '"ld": {"main": {"flv": "https://cdn/ld.flv"}},'
                                '"ao": {"main": {"flv": "https://cdn/audio.flv"}}'
                                "}}"
                            ),
                            "options": {
                                "qualities": [
                                    {"sdk_key": "hd", "level": 3},
                                    {"sdk_key": "ld", "level": 1},
                                ]
                            },
                        }
                    },
                    "flv_pull_url": {
                        "HD1": "https://cdn/hd.flv",
                        "SD1": "https://cdn/sd.flv",
                    },
                },
            },
            "status_code": 0,
        },
    )

    assert api.get_live_url_candidates("123", user="creator") == [
        "https://cdn/hd.flv",
        "https://cdn/ld.flv",
        "https://cdn/audio.flv",
        "https://cdn/sd.flv",
    ]


def test_get_room_id_from_user_uses_api_timeout():
    api = TikTokAPI.__new__(TikTokAPI)
    api._http_lock = __import__("threading").Lock()
    seen = {}

    def fake_http_get(url, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        response = MagicMock()
        response.text = '{"data": {"user": {"roomId": "123"}}}'
        response.json.return_value = {"data": {"user": {"roomId": "123"}}}
        return response

    api.http_client = MagicMock()
    api.http_client.get = fake_http_get
    api._tikrec_get_room_id_signed_url = lambda user: "https://www.tiktok.com/signed"

    assert api.get_room_id_from_user("creator") == "123"
    assert seen["timeout"] == (10, 20)


def test_old_get_room_id_from_user_returns_none_when_offline():
    api = TikTokAPI.__new__(TikTokAPI)
    api.EULER_API = "https://tiktok.eulerstream.com"
    api._http_lock = __import__("threading").Lock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"data": {"room_info": {}}}
    api._api_get = MagicMock(return_value=response)

    assert api._old_get_room_id_from_user("creator") is None


def test_get_room_id_from_user_falls_back_when_signed_fetch_fails():
    api = TikTokAPI.__new__(TikTokAPI)
    api._http_lock = __import__("threading").Lock()
    api._tikrec_warned_this_cycle = False
    api._tikrec_get_room_id_signed_url = lambda user: "https://www.tiktok.com/signed"
    api._api_get = MagicMock(
        side_effect=requests.ConnectionError("connection reset"),
    )
    api._old_get_room_id_from_user = MagicMock(return_value="room-99")

    assert api.get_room_id_from_user("creator") == "room-99"
    api._old_get_room_id_from_user.assert_called_once_with("creator")


def test_get_room_id_from_user_logs_tikrec_warning_once_per_cycle():
    api = TikTokAPI.__new__(TikTokAPI)
    api._http_lock = __import__("threading").Lock()
    api._tikrec_warned_this_cycle = False
    api._old_get_room_id_from_user = MagicMock(return_value=None)

    def fail_sign(_user):
        raise TikRecUnavailableError("503")

    api._tikrec_get_room_id_signed_url = fail_sign

    with patch("tiktok_live_recorder.core.tiktok_api.logger") as mock_logger:
        api.get_room_id_from_user("alpha")
        api.get_room_id_from_user("beta")

    assert mock_logger.warning.call_count == 1


def test_get_room_id_from_user_euler_non_200_raises_room_id_error():
    api = TikTokAPI.__new__(TikTokAPI)
    api.EULER_API = "https://tiktok.eulerstream.com"
    api._http_lock = __import__("threading").Lock()
    response = MagicMock()
    response.status_code = 500
    api._api_get = MagicMock(return_value=response)

    with pytest.raises(UserLiveError, match="Error extracting RoomID"):
        api._old_get_room_id_from_user("creator")
