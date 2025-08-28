from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.services.wire_capture_service import WireCapture


def _mk_ctx() -> RequestContext:
    return RequestContext(
        headers={}, cookies={}, state=None, app_state=None, client_host="127.0.0.1"
    )


@pytest.mark.asyncio
async def test_wire_capture_writes_request_and_reply(tmp_path: Any) -> None:
    file_path = tmp_path / "capture.log"
    cfg = AppConfig()
    cfg.logging.capture_file = str(file_path)
    cap = WireCapture(cfg)

    assert cap.enabled() is True

    await cap.capture_outbound_request(
        context=_mk_ctx(),
        session_id="sess-1",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        request_payload={"messages": [{"role": "user", "content": "hi"}]},
    )

    await cap.capture_inbound_response(
        context=_mk_ctx(),
        session_id="sess-1",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        response_content={
            "choices": [{"message": {"role": "assistant", "content": "hello"}}]
        },
    )

    text = file_path.read_text(encoding="utf-8")
    assert "----- REQUEST" in text
    assert "client=127.0.0.1" in text
    assert "backend=openai" in text
    assert "model=gpt-4" in text
    assert '"role": "user"' in text
    assert "----- REPLY" in text
    assert '"role": "assistant"' in text


@pytest.mark.asyncio
async def test_wire_capture_wraps_stream(tmp_path: Any) -> None:
    file_path = tmp_path / "capture_stream.log"
    cfg = AppConfig()
    cfg.logging.capture_file = str(file_path)
    cap = WireCapture(cfg)

    async def gen() -> AsyncIterator[bytes]:
        yield b"data: first\n\n"
        yield b"data: second\n\n"

    wrapped = cap.wrap_inbound_stream(
        context=_mk_ctx(),
        session_id="sess-2",
        backend="anthropic",
        model="claude",
        key_name="ANTHROPIC_API_KEY",
        stream=gen(),
    )

    out: list[bytes] = []
    async for chunk in wrapped:
        out.append(chunk)

    assert out == [b"data: first\n\n", b"data: second\n\n"]

    text = file_path.read_text(encoding="utf-8")
    assert "----- REPLY-STREAM" in text
    assert "backend=anthropic" in text
    assert "model=claude" in text
    assert "data: first" in text
    assert "data: second" in text


@pytest.mark.asyncio
async def test_wire_capture_rotation_and_truncate(tmp_path: Any) -> None:
    # Configure tiny max size and truncation for capture
    file_path = tmp_path / "rotate.log"
    cfg = AppConfig()
    cfg.logging.capture_file = str(file_path)
    cfg.logging.capture_max_bytes = 100
    cfg.logging.capture_truncate_bytes = 10
    cfg.logging.capture_max_files = 2
    cap = WireCapture(cfg)

    # Write a request longer than truncate threshold
    await cap.capture_outbound_request(
        context=_mk_ctx(),
        session_id="s",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        request_payload={
            "messages": [{"role": "user", "content": "0123456789ABCDEFGHIJ"}]
        },
    )

    # Stream some chunks that will be truncated in capture
    async def gen() -> AsyncIterator[bytes]:
        yield b"0123456789ABCDEFGHIJ\n"

    wrapped = cap.wrap_inbound_stream(
        context=_mk_ctx(),
        session_id="s",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        stream=gen(),
    )
    async for _ in wrapped:
        pass

    # Trigger rotation by another write if needed
    await cap.capture_inbound_response(
        context=_mk_ctx(),
        session_id="s",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        response_content={"ok": True},
    )

    # Current file should exist; rotated file may exist if rotation occurred
    assert file_path.exists()
    rotated_file = file_path.with_suffix(file_path.suffix + ".1")

    if rotated_file.exists():
        # If rotation occurred, the truncated content is in the rotated file.
        text = rotated_file.read_text(encoding="utf-8")
        assert "[[truncated]]" in text

    # Add time-based rotation test
    cfg2 = AppConfig()
    file_path2 = tmp_path / "time_rotate.log"
    cfg2.logging.capture_file = str(file_path2)
    cfg2.logging.capture_rotate_interval_seconds = 0
    cfg2.logging.capture_max_files = 1
    cap2 = WireCapture(cfg2)
    await cap2.capture_outbound_request(
        context=_mk_ctx(),
        session_id="s",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        request_payload={"a": 1},
    )
    await cap2.capture_inbound_response(
        context=_mk_ctx(),
        session_id="s",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        response_content={"ok": True},
    )
    assert file_path2.exists()
    assert file_path2.with_suffix(file_path2.suffix + ".1").exists()

    # Total cap test: ensure sizes do not exceed
    cfg3 = AppConfig()
    file_path3 = tmp_path / "total_cap.log"
    cfg3.logging.capture_file = str(file_path3)
    cfg3.logging.capture_max_bytes = 20
    cfg3.logging.capture_max_files = 5
    cfg3.logging.capture_total_max_bytes = 60
    cap3 = WireCapture(cfg3)
    for i in range(6):
        await cap3.capture_outbound_request(
            context=_mk_ctx(),
            session_id="s",
            backend="openai",
            model="gpt-4",
            key_name="OPENAI_API_KEY",
            request_payload={"i": i, "payload": "x" * 50},
        )
    total = 0
    if file_path3.exists():
        total += file_path3.stat().st_size
    for i in range(1, 20):
        p = file_path3.with_name(file_path3.name + f".{i}")
        if p.exists():
            total += p.stat().st_size
    assert total <= cfg3.logging.capture_total_max_bytes
