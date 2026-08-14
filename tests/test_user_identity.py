"""Tests for watchlist identity tracking (username changes / secUid)."""

from __future__ import annotations

import json
from pathlib import Path

from unittest.mock import MagicMock

import pytest

from tiktok_live_recorder.core.tiktok_api import UserRoomInfo
from tiktok_live_recorder.core.tiktok_recorder import TikTokRecorder
from tiktok_live_recorder.utils.recorder_config import RecorderConfig
from tiktok_live_recorder.utils.enums import Mode
from tiktok_live_recorder.utils.utils import (
    get_user_identity,
    prune_user_identities,
    read_user_identities,
    remove_user_identity,
    upsert_user_identity,
    write_user_identities,
)


@pytest.fixture
def identities_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("TIKTOK_RECORDER_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_upsert_and_read_user_identity(identities_dir):
    upsert_user_identity("alice", unique_id="alice_v2", sec_uid="SEC1")
    stored = read_user_identities()
    assert stored["alice"] == {"uniqueId": "alice_v2", "secUid": "SEC1"}
    assert get_user_identity("Alice") == {"uniqueId": "alice_v2", "secUid": "SEC1"}


def test_prune_and_remove_user_identity(identities_dir):
    upsert_user_identity("alice", unique_id="alice_v2", sec_uid="SEC1")
    upsert_user_identity("bob", unique_id="bob", sec_uid="SEC2")
    prune_user_identities(["alice"])
    assert set(read_user_identities()) == {"alice"}
    remove_user_identity("alice")
    assert read_user_identities() == {}


def test_users_json_format_unchanged_by_identity_sidecar(identities_dir):
    users_file = identities_dir / "users.json"
    users_file.write_text('{"users": ["alice"]}\n', encoding="utf-8")
    upsert_user_identity("alice", unique_id="alice_v2", sec_uid="SEC1")
    assert json.loads(users_file.read_text(encoding="utf-8")) == {"users": ["alice"]}
    assert (identities_dir / "user_identities.json").exists()


class IdentityFakeAPI:
    def __init__(
        self,
        rooms: dict[str, UserRoomInfo],
        profiles: dict | None = None,
        sec_uid_map: dict | None = None,
    ):
        self.rooms = rooms
        self.profiles = profiles or {}
        self.sec_uid_map = sec_uid_map or {}
        self.room_calls: list[str] = []
        self.alive_calls: list[tuple[str, str | None]] = []
        self.resolve_calls: list[str] = []

    def reset_tikrec_warn_flag(self):
        return None

    def get_user_room_info(self, user):
        self.room_calls.append(user)
        return self.rooms.get(user, UserRoomInfo())

    def get_user_identity_from_profile(self, user):
        return self.profiles.get(user)

    def resolve_unique_id_from_sec_uid(self, sec_uid):
        self.resolve_calls.append(sec_uid)
        return self.sec_uid_map.get(sec_uid)

    def is_room_alive(self, room_id, user=None):
        self.alive_calls.append((room_id, user))
        return bool(room_id)


def test_check_user_live_follows_renamed_handle(identities_dir, monkeypatch):
    upsert_user_identity(
        "alice",
        unique_id="alice_v2",
        sec_uid="SEC_ALICE",
        unique_id_resolved_at=__import__("time").time(),
    )
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alice"], cookies={})
    )
    fake = IdentityFakeAPI(
        {
            "alice_v2": UserRoomInfo(
                room_id="room-1",
                unique_id="alice_v2",
                sec_uid="SEC_ALICE",
            )
        }
    )
    recorder.tiktok = fake
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    assert recorder._check_user_live("alice") == "room-1"
    assert fake.room_calls == ["alice_v2"]
    assert fake.resolve_calls == []
    assert fake.alive_calls == [("room-1", "alice_v2")]
    assert recorder._lookup_users["alice"] == "alice_v2"


def test_check_user_live_updates_identity_on_rename(
    identities_dir, monkeypatch, caplog
):
    import logging

    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alice"], cookies={})
    )
    fake = IdentityFakeAPI(
        {
            "alice": UserRoomInfo(
                room_id="room-1",
                unique_id="alice_v2",
                sec_uid="SEC_ALICE",
            )
        }
    )
    recorder.tiktok = fake
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    with caplog.at_level(logging.INFO):
        assert recorder._check_user_live("alice") == "room-1"

    assert get_user_identity("alice") == {
        "uniqueId": "alice_v2",
        "secUid": "SEC_ALICE",
    }
    assert "@alice is now @alice_v2" in caplog.text


def test_check_user_live_rejects_recycled_handle(identities_dir, monkeypatch, caplog):
    import logging

    upsert_user_identity(
        "alice",
        unique_id="alice",
        sec_uid="SEC_ORIGINAL",
        unique_id_resolved_at=__import__("time").time(),
    )
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alice"], cookies={})
    )
    fake = IdentityFakeAPI(
        {
            "alice": UserRoomInfo(
                room_id="room-other",
                unique_id="alice",
                sec_uid="SEC_OTHER",
            )
        }
    )
    recorder.tiktok = fake
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    with caplog.at_level(logging.WARNING):
        assert recorder._check_user_live("alice") is None

    assert "different account" in caplog.text
    # Stored identity must not be overwritten by the recycled handle.
    assert get_user_identity("alice")["secUid"] == "SEC_ORIGINAL"


def test_check_user_live_recovers_via_secuid_resolver(
    identities_dir, monkeypatch, caplog
):
    import logging

    upsert_user_identity(
        "alice",
        unique_id="alice",
        sec_uid="SEC_ALICE",
        unique_id_resolved_at=__import__("time").time(),
    )
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alice"], cookies={})
    )
    fake = IdentityFakeAPI(
        rooms={
            "alice": UserRoomInfo(
                room_id="room-impostor",
                unique_id="alice",
                sec_uid="SEC_OTHER",
            ),
            "alice_v2": UserRoomInfo(
                room_id="room-1",
                unique_id="alice_v2",
                sec_uid="SEC_ALICE",
            ),
        },
        sec_uid_map={"SEC_ALICE": "alice_v2"},
    )
    recorder.tiktok = fake
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    with caplog.at_level(logging.INFO):
        assert recorder._check_user_live("alice") == "room-1"

    assert "SEC_ALICE" in fake.resolve_calls
    assert "alice_v2" in fake.room_calls
    assert get_user_identity("alice")["uniqueId"] == "alice_v2"
    assert get_user_identity("alice")["secUid"] == "SEC_ALICE"
    assert "@alice is now @alice_v2" in caplog.text


def test_secuid_resolver_runs_when_ttl_expired(identities_dir, monkeypatch):
    upsert_user_identity(
        "alice",
        unique_id="alice_old",
        sec_uid="SEC_ALICE",
        unique_id_resolved_at=0,
    )
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alice"], cookies={})
    )
    fake = IdentityFakeAPI(
        rooms={
            "alice_v2": UserRoomInfo(
                room_id="room-1",
                unique_id="alice_v2",
                sec_uid="SEC_ALICE",
            )
        },
        sec_uid_map={"SEC_ALICE": "alice_v2"},
    )
    recorder.tiktok = fake
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    assert recorder._check_user_live("alice") == "room-1"
    assert fake.resolve_calls == ["SEC_ALICE"]
    assert fake.room_calls[0] == "alice_v2"
    assert get_user_identity("alice")["uniqueIdResolvedAt"] > 0


def test_check_user_live_profile_fallback_discovers_rename(identities_dir, monkeypatch):
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alice"], cookies={})
    )
    fake = IdentityFakeAPI(
        rooms={
            "alice": UserRoomInfo(),
            "alice_v2": UserRoomInfo(
                room_id="room-9",
                unique_id="alice_v2",
                sec_uid="SEC_ALICE",
            ),
        },
        profiles={
            "alice": {"uniqueId": "alice_v2", "secUid": "SEC_ALICE"},
        },
    )
    recorder.tiktok = fake
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    assert recorder._check_user_live("alice") == "room-9"
    assert fake.room_calls == ["alice", "alice_v2"]
    assert get_user_identity("alice")["uniqueId"] == "alice_v2"


def test_spawn_recording_keeps_output_under_original_name(
    identities_dir, tmp_path, monkeypatch
):
    upsert_user_identity("alice", unique_id="alice_v2", sec_uid="SEC_ALICE")
    monkeypatch.setattr(
        "tiktok_live_recorder.utils.utils.default_output_base",
        lambda: tmp_path,
    )
    recorder = TikTokRecorder(
        RecorderConfig(
            mode=Mode.WATCHLIST,
            users=["alice"],
            output=None,
            cookies={},
        )
    )
    recorder._lookup_users["alice"] = "alice_v2"

    seen: dict[str, str] = {}

    def fake_start(user, room_id, lookup_user=None):
        seen["user"] = user
        seen["lookup"] = lookup_user
        seen["output"] = recorder._build_output_path(user)
        path = Path(seen["output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    recorder.start_recording = fake_start
    recorder._recording_worker("alice", "room-1", lookup_user="alice_v2")

    assert seen["user"] == "alice"
    assert seen["lookup"] == "alice_v2"
    assert Path(seen["output"]).parent.name == "alice"
    assert Path(seen["output"]).name.startswith("TK_alice_")


def test_status_includes_identities(identities_dir):
    upsert_user_identity("alice", unique_id="alice_v2", sec_uid="SEC_ALICE")
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alice"], cookies={})
    )
    status = recorder.get_status()
    assert status["identities"]["alice"]["uniqueId"] == "alice_v2"


def test_duplicate_sec_uid_skipped_in_poll(identities_dir, monkeypatch):
    write_user_identities(
        {
            "alice": {"uniqueId": "alice", "secUid": "SAME"},
            "alice_old": {"uniqueId": "alice_old", "secUid": "SAME"},
        }
    )
    recorder = TikTokRecorder(
        RecorderConfig(mode=Mode.WATCHLIST, users=["alice", "alice_old"], cookies={})
    )

    class DupAPI(IdentityFakeAPI):
        def get_user_room_info(self, user):
            self.room_calls.append(user)
            return UserRoomInfo(room_id=f"room-{user}", unique_id=user, sec_uid="SAME")

        def is_room_alive(self, room_id, user=None):
            return True

    recorder.tiktok = DupAPI({})
    spawned: list[str] = []

    def spawn(user, room_id, lookup_user=None):
        spawned.append(user)
        recorder._active_recordings[user] = {
            "thread": MagicMock(is_alive=MagicMock(return_value=True)),
            "room_id": room_id,
            "lookup_user": lookup_user or user,
            "status": "recording",
        }

    recorder._spawn_recording_thread = spawn
    monkeypatch.setattr(recorder, "_poll_user_order", lambda users: list(users))
    monkeypatch.setattr(
        "tiktok_live_recorder.core.tiktok_recorder.time.sleep", lambda *_: None
    )

    recorder._poll_users_once(["alice", "alice_old"], {}, label="Watchlist")

    # First user starts; second is skipped as duplicate secUid.
    assert spawned == ["alice"]
