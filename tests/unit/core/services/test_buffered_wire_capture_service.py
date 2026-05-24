from __future__ import annotations

from src.core.config.app_config import AppConfig
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.request_context import RequestContext
from src.core.services.buffered_wire_capture_service import BufferedWireCapture


def _with_b2bua_enabled(config: AppConfig) -> AppConfig:
    b2bua_config = config.session.b2bua.model_copy(update={"enabled": True})
    session_config = config.session.model_copy(update={"b2bua": b2bua_config})
    return config.model_copy(update={"session": session_config})


def _with_b2bua_disabled(config: AppConfig) -> AppConfig:
    b2bua_config = config.session.b2bua.model_copy(update={"enabled": False})
    session_config = config.session.model_copy(update={"b2bua": b2bua_config})
    return config.model_copy(update={"session": session_config})


async def test_create_entry_generates_session_id_when_missing() -> None:
    service = BufferedWireCapture(_with_b2bua_disabled(AppConfig()))
    context = RequestContext(
        headers={},
        cookies={},
        state=object(),
        app_state=object(),
        client_host="localhost",
        agent="test-agent",
        request_id="req-123",
    )
    entry = await service._create_entry(  # type: ignore[attr-defined]
        direction="test",
        source="src",
        destination="dest",
        context=context,
        session_id=None,
        backend="backend",
        model="model",
        key_name=None,
        payload={"hello": "world"},
    )
    assert entry.session_id == "req-123"


async def test_create_entry_generates_uuid_when_context_missing_request_id() -> None:
    service = BufferedWireCapture(AppConfig())
    entry = await service._create_entry(  # type: ignore[attr-defined]
        direction="test",
        source="src",
        destination="dest",
        context=None,
        session_id=None,
        backend="backend",
        model="model",
        key_name=None,
        payload={"hello": "world"},
    )
    assert entry.session_id


async def test_create_entry_handles_nonserializable_payload_for_length() -> None:
    service = BufferedWireCapture(AppConfig())
    entry = await service._create_entry(  # type: ignore[attr-defined]
        direction="test",
        source="src",
        destination="dest",
        context=None,
        session_id=None,
        backend="backend",
        model="model",
        key_name=None,
        payload={"hello": object()},
    )
    assert isinstance(entry.content_length, int)


async def test_create_entry_avoids_request_id_fallback_when_b2bua_enabled() -> None:
    config = _with_b2bua_enabled(AppConfig())
    service = BufferedWireCapture(config)
    context = RequestContext(
        headers={},
        cookies={},
        state=object(),
        app_state=object(),
        client_host="localhost",
        request_id="req-no-fallback",
    )
    entry = await service._create_entry(  # type: ignore[attr-defined]
        direction="test",
        source="src",
        destination="dest",
        context=context,
        session_id=None,
        backend="backend",
        model="model",
        key_name=None,
        payload={"hello": "world"},
    )
    assert entry.session_id != "req-no-fallback"
    await service.shutdown()


async def test_create_entry_carries_b2bua_identity_metadata() -> None:
    config = _with_b2bua_enabled(AppConfig())
    service = BufferedWireCapture(config)
    context = RequestContext(
        headers={},
        cookies={},
        state=object(),
        app_state=object(),
        client_host="localhost",
        request_id="req-b2bua",
        session_id="llm-b2bua-a-7777",
        b2bua_identity=B2buaIdentity(
            a_session_id="llm-b2bua-a-7777",
            b_session_id="llm-b2bua-b-7777-2",
            b_seq=2,
        ),
    )
    entry = await service._create_entry(  # type: ignore[attr-defined]
        direction="test",
        source="src",
        destination="dest",
        context=context,
        session_id=None,
        backend="backend",
        model="model",
        key_name=None,
        payload={"hello": "world"},
    )
    assert entry.session_id == "llm-b2bua-a-7777"
    assert entry.metadata["a_session_id"] == "llm-b2bua-a-7777"
    assert entry.metadata["b_session_id"] == "llm-b2bua-b-7777-2"
    assert entry.metadata["b_seq"] == 2
    await service.shutdown()
