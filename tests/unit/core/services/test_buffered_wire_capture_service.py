from __future__ import annotations

from types import SimpleNamespace

from src.core.config.app_config import AppConfig
from src.core.services.buffered_wire_capture_service import BufferedWireCapture


def test_create_entry_generates_session_id_when_missing() -> None:
    service = BufferedWireCapture(AppConfig())
    context = SimpleNamespace(
        client_host="localhost", agent="test-agent", request_id="req-123"
    )
    entry = service._create_entry(  # type: ignore[attr-defined]
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


def test_create_entry_generates_uuid_when_context_missing_request_id() -> None:
    service = BufferedWireCapture(AppConfig())
    entry = service._create_entry(  # type: ignore[attr-defined]
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
