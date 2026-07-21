import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.tiktok_api import (  # noqa: E402
    collect_stream_urls_from_obj,
    extract_embedded_json_from_page,
    extract_user_live_context_from_obj,
    extract_user_live_context_from_page,
    is_audio_only_stream_url,
    order_stream_urls,
    pick_preferred_stream_url,
)
from utils.utils import cookie_key_summary, has_session_cookie  # noqa: E402


def test_has_session_cookie_accepts_sessionid_only():
    assert has_session_cookie({"sessionid": "abc123"}) is True


def test_has_session_cookie_accepts_sessionid_ss_only():
    assert has_session_cookie({"sessionid_ss": "abc123"}) is True


def test_has_session_cookie_rejects_empty():
    assert has_session_cookie({}) is False
    assert has_session_cookie({"sessionid": "", "sessionid_ss": ""}) is False


def test_cookie_key_summary_lists_tracked_keys():
    summary = cookie_key_summary(
        {"sessionid": "a", "sessionid_ss": "", "tt-target-idc": "useast2a"}
    )
    assert "sessionid=yes" in summary
    assert "sessionid_ss=no" in summary
    assert "tt-target-idc=yes" in summary


def test_collect_stream_urls_from_nested_json():
    payload = {
        "data": {
            "stream": {
                "main": {
                    "flv": "https://cdn.example.com/live_or4.flv",
                    "hls": "https://cdn.example.com/live.m3u8",
                }
            }
        }
    }

    urls = collect_stream_urls_from_obj(payload)
    assert "https://cdn.example.com/live_or4.flv" in urls
    assert "https://cdn.example.com/live.m3u8" in urls


def test_pick_preferred_stream_url_prefers_flv_over_hls():
    urls = [
        "https://cdn.example.com/live.m3u8",
        "https://cdn.example.com/live_sd.flv",
    ]
    assert pick_preferred_stream_url(urls) == "https://cdn.example.com/live_sd.flv"


def test_pick_preferred_stream_url_prefers_or4_quality():
    urls = [
        "https://cdn.example.com/live_hd.flv",
        "https://cdn.example.com/live_or4.flv",
    ]
    assert pick_preferred_stream_url(urls) == "https://cdn.example.com/live_or4.flv"


def test_extract_embedded_json_from_sigi_state():
    html = """
    <html>
      <script id="SIGI_STATE" type="application/json">
        {"LiveRoom": {"status": 2, "owner": {"uniqueId": "creator"}, "stream": {"flv": "https://cdn.example.com/sigior4.flv"}}}
      </script>
    </html>
    """
    blobs = extract_embedded_json_from_page(html)
    context = extract_user_live_context_from_obj(blobs[0], "creator")
    assert context is not None
    assert context["stream_urls"] == ["https://cdn.example.com/sigior4.flv"]


def test_extract_user_live_context_ignores_recommended_streams_for_offline_user():
    payload = {
        "LiveRoom": {
            "status": 4,
            "owner": {"uniqueId": "offline_user"},
            "stream_url": {"flv_pull_url": {"HD1": "https://cdn.example.com/stale.flv"}},
        },
        "SuggestedLives": [
            {
                "owner": {"uniqueId": "blackwidowink.la"},
                "status": 2,
                "stream": {"flv": "https://cdn.example.com/recommended_or4.flv"},
            }
        ],
    }

    assert extract_user_live_context_from_obj(payload, "offline_user") is None


def test_extract_user_live_context_matches_room_id_when_provided():
    payload = {
        "room": {
            "status": 2,
            "roomId": "999",
            "owner": {"uniqueId": "creator"},
            "pull": {"flv": "https://cdn.example.com/wrong_room.flv"},
        }
    }

    assert extract_user_live_context_from_obj(payload, "creator", room_id="123") is None

    context = extract_user_live_context_from_obj(payload, "creator", room_id="999")
    assert context["stream_urls"] == ["https://cdn.example.com/wrong_room.flv"]


def test_extract_user_live_context_from_page_requires_owner_match():
    html = """
    <html>
      <script id="SIGI_STATE" type="application/json">
        {
          "LiveRoom": {"status": 4, "owner": {"uniqueId": "offline_user"}},
          "Feed": {"flv": "https://cdn.example.com/suggested_or4.flv"}
        }
      </script>
    </html>
    """
    assert extract_user_live_context_from_page(html, "offline_user") is None


def test_extract_live_room_user_info_with_stream_data_payload():
    stream_data = json.dumps(
        {
            "data": {
                "hd": {"main": {"flv": "https://cdn.example.com/cri3_hd.flv"}},
                "ld": {"main": {"flv": "https://cdn.example.com/cri3_ld.flv"}},
            }
        }
    )
    payload = {
        "LiveRoom": {
            "liveRoomStatus": 0,
            "liveRoomUserInfo": {
                "user": {
                    "uniqueId": "cri3_x",
                    "status": 2,
                    "roomId": "7664014352193735454",
                },
                "liveRoom": {
                    "status": 2,
                    "streamData": {"pull_data": {"stream_data": stream_data}},
                },
            },
        },
        "SuggestedLives": [
            {
                "owner": {"uniqueId": "other_creator"},
                "status": 2,
                "stream": {"flv": "https://cdn.example.com/other_or4.flv"},
            }
        ],
    }

    context = extract_user_live_context_from_obj(
        payload, "cri3_x", room_id="7664014352193735454"
    )
    assert context is not None
    assert context["stream_urls"][0] == "https://cdn.example.com/cri3_hd.flv"
    assert "https://cdn.example.com/cri3_hd.flv" in context["stream_urls"]
    assert "https://cdn.example.com/other_or4.flv" not in context["stream_urls"]


def test_is_audio_only_stream_url_detects_only_audio_query():
    assert is_audio_only_stream_url(
        "https://cdn.example.com/stream.flv?only_audio=1&sign=abc"
    )
    assert not is_audio_only_stream_url("https://cdn.example.com/stream_hd.flv")


def test_order_stream_urls_prefers_hd_and_drops_audio():
    urls = [
        "https://cdn.example.com/stream.flv?only_audio=1",
        "https://cdn.example.com/stream_ld.flv",
        "https://cdn.example.com/stream_hd.flv",
    ]
    assert order_stream_urls(urls) == [
        "https://cdn.example.com/stream_hd.flv",
        "https://cdn.example.com/stream_ld.flv",
    ]


def test_collect_stream_urls_skips_ao_sdk_track():
    stream_data = json.dumps(
        {
            "data": {
                "ao": {
                    "main": {
                        "flv": "https://cdn.example.com/only.flv?only_audio=1",
                    }
                },
                "hd": {"main": {"flv": "https://cdn.example.com/video_hd.flv"}},
                "ld": {"main": {"flv": "https://cdn.example.com/video_ld.flv"}},
            }
        }
    )
    urls = collect_stream_urls_from_obj({"pull_data": {"stream_data": stream_data}})
    assert urls == [
        "https://cdn.example.com/video_hd.flv",
        "https://cdn.example.com/video_ld.flv",
    ]
