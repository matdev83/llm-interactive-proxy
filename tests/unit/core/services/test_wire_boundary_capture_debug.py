from __future__ import annotations

import json

import pytest
from src.core.services.wire_boundary_capture import build_outbound_capture_debug


def test_build_outbound_capture_debug_extracts_long_instructions_tail() -> None:
    prefix = "a" * 3000
    steering = "DROID_INCOMPATIBLE_TOOL_STEERING_MARKER"
    instructions = prefix + steering
    payload = json.dumps(
        {"type": "response.create", "model": "x", "instructions": instructions}
    ).encode("utf-8")
    debug = build_outbound_capture_debug(payload)
    assert debug is not None
    assert debug["ws_event_type"] == "response.create"
    assert debug["instructions_len"] == len(instructions)
    assert steering in debug["instructions_suffix"]
    assert debug["instructions_prefix"] == instructions[:128]


def test_build_outbound_capture_debug_stores_full_short_instructions() -> None:
    instructions = "short"
    payload = json.dumps({"instructions": instructions}).encode("utf-8")
    debug = build_outbound_capture_debug(payload)
    assert debug == {
        "instructions_len": 5,
        "instructions": "short",
    }


def test_build_outbound_capture_debug_handles_input_list() -> None:
    payload = json.dumps(
        {"type": "x", "input": [{"role": "user", "content": "hi"}]}
    ).encode("utf-8")
    debug = build_outbound_capture_debug(payload)
    assert debug is not None
    assert debug["ws_event_type"] == "x"
    assert debug["input_list_len"] == 1


@pytest.mark.parametrize(
    "raw",
    [b"", b"{", b"not-json", b"\xff\xff"],
)
def test_build_outbound_capture_debug_returns_none_on_non_json(raw: bytes) -> None:
    assert build_outbound_capture_debug(raw) is None
