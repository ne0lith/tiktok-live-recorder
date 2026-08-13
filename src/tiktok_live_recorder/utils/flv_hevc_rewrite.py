"""Rewrite legacy FLV HEVC (codec id 12) tags to Enhanced RTMP hvc1 for older ffmpeg."""

from __future__ import annotations

import struct
from pathlib import Path

FLV_CODECID_X_HEVC = 12
FLV_IS_EX_HEADER = 0x80
PACKET_TYPE_SEQUENCE_START = 0
PACKET_TYPE_CODED_FRAMES = 1


def _read_flv_tag_header(data: bytes, offset: int) -> tuple[int, int, int] | None:
    if offset + 11 > len(data):
        return None
    tag_type = data[offset]
    data_size = (data[offset + 1] << 16) | (data[offset + 2] << 8) | data[offset + 3]
    timestamp = (
        (data[offset + 4] << 16)
        | (data[offset + 5] << 8)
        | data[offset + 6]
        | (data[offset + 7] << 24)
    )
    return tag_type, data_size, timestamp


def _write_flv_tag_header(tag_type: int, data_size: int, timestamp: int) -> bytes:
    header = struct.pack(
        ">BBBIB",
        tag_type,
        (data_size >> 16) & 0xFF,
        (data_size >> 8) & 0xFF,
        data_size & 0xFF,
        (timestamp >> 16) & 0xFF,
    )
    header += struct.pack(
        ">BBB",
        (timestamp >> 8) & 0xFF,
        timestamp & 0xFF,
        (timestamp >> 24) & 0xFF,
    )
    header += b"\x00\x00\x00"
    return header


def rewrite_legacy_hevc_video_body(body: bytes) -> bytes:
    if len(body) < 2:
        return body

    frame_type = body[0] & 0xF0
    codec_id = body[0] & 0x0F
    if codec_id != FLV_CODECID_X_HEVC:
        return body

    packet_type = body[1]
    if packet_type == PACKET_TYPE_SEQUENCE_START:
        payload = body[2:]
        header_byte = FLV_IS_EX_HEADER | frame_type | PACKET_TYPE_SEQUENCE_START
        return bytes([header_byte]) + b"hvc1" + payload

    if packet_type == PACKET_TYPE_CODED_FRAMES:
        if len(body) < 5:
            return body
        cts = body[2:5]
        payload = body[5:]
        header_byte = FLV_IS_EX_HEADER | frame_type | PACKET_TYPE_CODED_FRAMES
        return bytes([header_byte]) + b"hvc1" + cts + payload

    return body


def rewrite_legacy_hevc_flv(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    if len(data) < 9 or data[0:3] != b"FLV":
        destination.write_bytes(data)
        return

    out = bytearray()
    out.extend(data[0:9])
    offset = 9

    while offset + 4 <= len(data):
        prev_tag_size = struct.unpack(">I", data[offset : offset + 4])[0]
        offset += 4
        if offset >= len(data):
            break

        parsed = _read_flv_tag_header(data, offset)
        if parsed is None:
            break
        tag_type, data_size, timestamp = parsed
        body_start = offset + 11
        body_end = body_start + data_size
        if body_end > len(data):
            break

        body = data[body_start:body_end]
        if tag_type == 9:
            body = rewrite_legacy_hevc_video_body(body)

        tag_header = _write_flv_tag_header(tag_type, len(body), timestamp)
        out.extend(tag_header)
        out.extend(body)
        out.extend(struct.pack(">I", 11 + len(body)))
        offset = body_end + 4

        if prev_tag_size == 0 and offset == 13 + 4 + 11 + data_size + 4:
            continue
        if offset >= len(data) and prev_tag_size == 0:
            break

    destination.write_bytes(out)


def file_needs_legacy_hevc_rewrite(path: str | Path) -> bool:
    """Heuristic: first video tag uses legacy codec id 12."""
    data = Path(path).read_bytes()
    if len(data) < 9 or data[0:3] != b"FLV":
        return False
    offset = 9
    while offset + 15 <= len(data):
        offset += 4
        parsed = _read_flv_tag_header(data, offset)
        if parsed is None:
            return False
        tag_type, data_size, _timestamp = parsed
        body_start = offset + 11
        if tag_type == 9 and body_start < len(data):
            return (data[body_start] & 0x0F) == FLV_CODECID_X_HEVC
        offset = body_start + data_size + 4
    return False


def flv_has_video_tag(data: bytes) -> bool | None:
    """Return whether a buffer contains an FLV video tag.

    True: a complete video tag (type 9) is present.
    False: at least one complete tag was scanned and none were video.
    None: not FLV yet, or no complete tag in the buffer.
    """
    if len(data) < 13 or data[0:3] != b"FLV":
        return None
    offset = 9
    saw_complete_tag = False
    while offset + 15 <= len(data):
        offset += 4
        parsed = _read_flv_tag_header(data, offset)
        if parsed is None:
            break
        tag_type, data_size, _timestamp = parsed
        body_start = offset + 11
        body_end = body_start + data_size
        if body_end > len(data):
            break
        saw_complete_tag = True
        if tag_type == 9:
            return True
        offset = body_end
    if saw_complete_tag:
        return False
    return None
