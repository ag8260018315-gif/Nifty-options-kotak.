"""Criterion: 7207 and 7208 native-batch decoding honors dividers.

Builds synthetic little-endian 7207 (index) and 7208 level-1 (option) packets by hand
and asserts lib.kotak_feed.decode_packet() converts token/LTP/change/pct using the
supplied exchange divider, and that packet_frames() correctly splits two packets that
arrive concatenated in a single websocket frame (native-batch framing).

This exercises the pure decoding module directly (not the FastAPI app object), which
is the only way to reach binary websocket packet parsing without a live NSE session.
"""

import struct

from lib.kotak_feed import decode_packet, packet_frames


DIVIDER = 100  # nse_fo divider as advertised by Kotak's 1117 auth/divider control message


def _build_7207_index_packet(token: int, ltp_raw: int, change_pct_raw: int) -> bytes:
    """Message code 7207 index packet, matching lib/kotak_feed.py's offsets (len >= 87)."""
    length = 87
    buf = bytearray(length)
    struct.pack_into("<H", buf, 0, length)          # packet_length
    struct.pack_into("<H", buf, 2, 7207)             # message_code
    struct.pack_into("<b", buf, 4, 2)                # exchange_id 2 -> nse_fo
    buf[5] = 1                                        # level
    struct.pack_into("<I", buf, 9, token)            # token
    struct.pack_into("<i", buf, 13, 0)               # open
    struct.pack_into("<i", buf, 17, ltp_raw - 500)   # close (so change is derivable elsewhere)
    struct.pack_into("<i", buf, 21, 0)               # high
    struct.pack_into("<i", buf, 25, 0)               # low
    struct.pack_into("<i", buf, 29, ltp_raw)         # ltp
    struct.pack_into("<Q", buf, 33, 0)               # last_trade_time_raw
    struct.pack_into("<i", buf, 49, change_pct_raw)  # change_pct * 100
    name = b"NIFTY 50"
    buf[66:66 + len(name)] = name
    return bytes(buf)


def _build_7208_level1_option_packet(token: int, ltp_raw: int, change_raw: int) -> bytes:
    """Message code 7208 level-1 option packet, matching lib/kotak_feed.py (len >= 54)."""
    length = 54
    buf = bytearray(length)
    struct.pack_into("<H", buf, 0, length)
    struct.pack_into("<H", buf, 2, 7208)
    struct.pack_into("<b", buf, 4, 2)                # nse_fo
    buf[5] = 1                                        # level 1
    struct.pack_into("<I", buf, 9, token)
    struct.pack_into("<q", buf, 13, 0)               # last_trade_time_raw
    struct.pack_into("<I", buf, 21, ltp_raw)         # ltp (unsigned)
    struct.pack_into("<q", buf, 25, 0)               # ltq
    struct.pack_into("<I", buf, 33, 0)               # close_raw
    struct.pack_into("<i", buf, 37, 250)             # change_pct raw (2.50%)
    struct.pack_into("<i", buf, 41, change_raw)      # change
    return bytes(buf)


def test_decode_7207_index_packet_applies_divider():
    packet = _build_7207_index_packet(token=26000, ltp_raw=2_500_000, change_pct_raw=125)
    decoded = decode_packet(packet, {"nse_fo": DIVIDER})

    assert decoded is not None
    assert decoded["kind"] == "index"
    assert decoded["exchange"] == "nse_fo"
    assert decoded["token"] == "26000"
    assert decoded["ltp"] == 25000.0  # 2_500_000 / 100
    assert decoded["change_pct"] == 1.25  # 125 / 100


def test_decode_7208_level1_option_packet_applies_divider():
    packet = _build_7208_level1_option_packet(token=48521, ltp_raw=1_234_50, change_raw=500)
    decoded = decode_packet(packet, {"nse_fo": DIVIDER})

    assert decoded is not None
    assert decoded["kind"] == "option"
    assert decoded["token"] == "48521"
    assert decoded["ltp"] == 1234.5  # 123450 / 100
    assert decoded["change"] == 5.0  # 500 / 100


def test_decode_uses_default_divider_when_exchange_unmapped():
    packet = _build_7207_index_packet(token=26000, ltp_raw=2_500_000, change_pct_raw=125)
    decoded = decode_packet(packet, {})  # no dividers supplied yet -> default 100
    assert decoded is not None
    assert decoded["ltp"] == 25000.0


def test_packet_frames_splits_two_concatenated_native_batch_packets():
    index_packet = _build_7207_index_packet(token=26000, ltp_raw=2_500_000, change_pct_raw=125)
    option_packet = _build_7208_level1_option_packet(token=48521, ltp_raw=123450, change_raw=500)
    concatenated = index_packet + option_packet

    frames = packet_frames(concatenated)

    assert len(frames) == 2
    assert frames[0] == index_packet
    assert frames[1] == option_packet

    decoded_first = decode_packet(frames[0], {"nse_fo": DIVIDER})
    decoded_second = decode_packet(frames[1], {"nse_fo": DIVIDER})
    assert decoded_first["kind"] == "index"
    assert decoded_second["kind"] == "option"


def test_packet_frames_ignores_truncated_trailing_bytes():
    index_packet = _build_7207_index_packet(token=26000, ltp_raw=2_500_000, change_pct_raw=125)
    truncated_trailer = b"\x05\x00"  # declares length 5 but no body follows -> must be dropped, not crash
    frames = packet_frames(index_packet + truncated_trailer)
    assert len(frames) == 1
    assert frames[0] == index_packet
