from __future__ import annotations

import json

from src.connectors.kiro_oauth_auto.event_stream import AwsEventStreamDecoder


def _build_event_stream_message(*, event_type: str, payload_obj: object) -> bytes:
    payload = json.dumps(payload_obj).encode("utf-8")
    header_name = b":event-type"
    header_value = event_type.encode("utf-8")

    headers = bytearray()
    headers.append(len(header_name))
    headers.extend(header_name)
    headers.append(7)  # string
    headers.extend(len(header_value).to_bytes(2, "big"))
    headers.extend(header_value)

    total_length = 12 + len(headers) + len(payload) + 4
    prelude = (
        total_length.to_bytes(4, "big")
        + len(headers).to_bytes(4, "big")
        + (0).to_bytes(4, "big")  # prelude CRC (ignored by decoder)
    )
    message_crc = (0).to_bytes(4, "big")
    return prelude + bytes(headers) + payload + message_crc


def test_decoder_parses_single_message() -> None:
    msg = _build_event_stream_message(
        event_type="assistantResponseEvent",
        payload_obj={"assistantResponseEvent": {"content": "hi"}},
    )
    decoder = AwsEventStreamDecoder()
    out = decoder.feed(msg)
    assert len(out) == 1
    assert out[0].event_type == "assistantResponseEvent"
    assert out[0].json()["assistantResponseEvent"]["content"] == "hi"


def test_decoder_handles_fragmented_input() -> None:
    msg = _build_event_stream_message(
        event_type="toolUseEvent",
        payload_obj={
            "toolUseEvent": {
                "toolUseId": "t1",
                "name": "f",
                "input": "{}",
                "stop": True,
            }
        },
    )
    decoder = AwsEventStreamDecoder()
    first = msg[:10]
    second = msg[10:]
    assert decoder.feed(first) == []
    out = decoder.feed(second)
    assert len(out) == 1
    assert out[0].event_type == "toolUseEvent"
