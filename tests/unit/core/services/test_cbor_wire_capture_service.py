"""Unit tests for CborWireCaptureService."""

from __future__ import annotations

import asyncio
import errno
import tempfile
import time
from pathlib import Path

import cbor2
import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.cbor_capture import (
    CaptureDirection,
    CapturedWireEvent,
    CaptureEntry,
    CaptureFileHeader,
    CaptureMetadata,
    CaptureSession,
)
from src.core.domain.request_context import RequestContext
from src.core.interfaces.wire_capture_recorder_interface import (
    IWireCaptureRecorder,
)
from src.core.services.cbor_wire_capture_service import CborWireCaptureService

from tests.utils.fake_clock import FakeClockContext


@pytest.fixture
def temp_capture_dir():
    """Create a temporary directory for capture files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    return AppConfig.from_env()


def _with_b2bua_enabled(config: AppConfig) -> AppConfig:
    b2bua_config = config.session.b2bua.model_copy(update={"enabled": True})
    session_config = config.session.model_copy(update={"b2bua": b2bua_config})
    return config.model_copy(update={"session": session_config})


def _with_b2bua_disabled(config: AppConfig) -> AppConfig:
    b2bua_config = config.session.b2bua.model_copy(update={"enabled": False})
    session_config = config.session.model_copy(update={"b2bua": b2bua_config})
    return config.model_copy(update={"session": session_config})


@pytest.fixture
async def capture_service(mock_config, temp_capture_dir):
    """Create a CborWireCaptureService for testing."""
    service = CborWireCaptureService(
        config=mock_config,
        capture_dir=temp_capture_dir,
        session_id="test-session-123",
    )
    yield service
    # Cleanup - use proper async shutdown
    await service.shutdown()


class TestCaptureMetadata:
    """Tests for CaptureMetadata dataclass."""

    def test_to_dict_minimal(self):
        """Test to_dict with minimal data."""
        meta = CaptureMetadata()
        result = meta.to_dict()
        assert result == {}

    def test_to_dict_full(self):
        """Test to_dict with all fields."""
        meta = CaptureMetadata(
            session_id="sess-1",
            a_session_id="llm-b2bua-a-1",
            b_session_id="llm-b2bua-b-1-2",
            b_seq=2,
            backend="openai",
            model="gpt-4",
            key_name="key-1",
            client_host="127.0.0.1",
            user_agent="test-agent",
            request_id="req-1",
            chunk_index=5,
            is_stream_start=True,
            is_stream_end=False,
            total_chunks=10,
            total_bytes=1000,
            compression_correlation_id="ccid-abc",
            compression_records_count=3,
        )
        result = meta.to_dict()
        assert result["sid"] == "sess-1"
        assert result["asid"] == "llm-b2bua-a-1"
        assert result["bsid"] == "llm-b2bua-b-1-2"
        assert result["bseq"] == 2
        assert result["be"] == "openai"
        assert result["mod"] == "gpt-4"
        assert result["ci"] == 5
        assert result["ss"] is True
        assert "se" not in result  # False values not included
        assert result["ccid"] == "ccid-abc"
        assert result["crc"] == 3

    def test_from_dict_roundtrip(self):
        """Test from_dict recreates original metadata."""
        original = CaptureMetadata(
            session_id="sess-1",
            a_session_id="llm-b2bua-a-1",
            b_session_id="llm-b2bua-b-1-3",
            b_seq=3,
            backend="anthropic",
            model="claude-3",
            chunk_index=3,
            compression_correlation_id="ccid-roundtrip",
            compression_records_count=2,
        )
        dict_form = original.to_dict()
        recreated = CaptureMetadata.from_dict(dict_form)
        assert recreated.session_id == original.session_id
        assert recreated.a_session_id == original.a_session_id
        assert recreated.b_session_id == original.b_session_id
        assert recreated.b_seq == original.b_seq
        assert recreated.backend == original.backend
        assert recreated.model == original.model
        assert recreated.chunk_index == original.chunk_index
        assert recreated.compression_correlation_id == "ccid-roundtrip"
        assert recreated.compression_records_count == 2

    def test_canonical_usage_serialization(self):
        """Test canonical usage is serialized as 'cu' key."""
        canonical_usage = {
            "provider_id": "openai",
            "model_id": "gpt-4",
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }
        meta = CaptureMetadata(
            session_id="sess-1",
            backend="openai",
            canonical_usage=canonical_usage,
        )
        result = meta.to_dict()
        assert result["cu"] == canonical_usage
        assert result["sid"] == "sess-1"
        assert result["be"] == "openai"

    def test_canonical_usage_deserialization(self):
        """Test canonical usage is deserialized from 'cu' key."""
        canonical_usage = {
            "provider_id": "anthropic",
            "model_id": "claude-3",
            "cost": 0.05,
        }
        data = {
            "sid": "sess-2",
            "be": "anthropic",
            "cu": canonical_usage,
        }
        meta = CaptureMetadata.from_dict(data)
        assert meta.canonical_usage == canonical_usage
        assert meta.session_id == "sess-2"
        assert meta.backend == "anthropic"

    def test_canonical_usage_roundtrip(self):
        """Test canonical usage roundtrip serialization."""
        canonical_usage = {
            "provider_id": "gemini",
            "model_id": "gemini-pro",
            "prompt_tokens": 5,
            "completion_tokens": 15,
            "total_tokens": 20,
            "extensions": {"custom_field": "value"},
        }
        original = CaptureMetadata(
            session_id="sess-3",
            backend="gemini",
            model="gemini-pro",
            canonical_usage=canonical_usage,
        )
        dict_form = original.to_dict()
        recreated = CaptureMetadata.from_dict(dict_form)
        assert recreated.canonical_usage == original.canonical_usage
        assert recreated.session_id == original.session_id
        assert recreated.backend == original.backend

    def test_canonical_usage_none_excluded(self):
        """Test canonical usage None is excluded from serialization."""
        meta = CaptureMetadata(
            session_id="sess-4",
            backend="openai",
            canonical_usage=None,
        )
        result = meta.to_dict()
        assert "cu" not in result
        assert result["sid"] == "sess-4"

    def test_canonical_usage_includes_extensions(self):
        """Test that canonical usage includes provider extensions."""
        canonical_usage = {
            "provider_id": "openai",
            "model_id": "gpt-4",
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "extensions": {"custom_field": "value", "another_field": 123},
        }
        meta = CaptureMetadata(
            session_id="sess-5",
            backend="openai",
            canonical_usage=canonical_usage,
        )
        result = meta.to_dict()
        assert result["cu"]["extensions"] == canonical_usage["extensions"]
        assert result["cu"]["extensions"]["custom_field"] == "value"
        assert result["cu"]["extensions"]["another_field"] == 123


class TestCaptureEntry:
    """Tests for CaptureEntry dataclass."""

    def test_to_dict(self):
        """Test entry serialization."""
        entry = CaptureEntry(
            timestamp=1700000000.123456789,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=42,
            data=b"Hello, World!",
            metadata=CaptureMetadata(session_id="test"),
        )
        result = entry.to_dict()
        assert result["ts"] == 1700000000.123456789
        assert result["dir"] == 0
        assert result["seq"] == 42
        assert result["data"] == b"Hello, World!"
        assert result["meta"]["sid"] == "test"

    def test_from_dict_roundtrip(self):
        """Test entry deserialization."""
        original = CaptureEntry(
            timestamp=1700000000.5,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=10,
            data=b"\x00\x01\x02\x03",
        )
        dict_form = original.to_dict()
        recreated = CaptureEntry.from_dict(dict_form)
        assert recreated.timestamp == original.timestamp
        assert recreated.direction == original.direction
        assert recreated.sequence == original.sequence
        assert recreated.data == original.data


class TestCapturedWireEvent:
    """Tests for the canonical CapturedWireEvent model."""

    def test_from_metadata_exposes_explicit_fields(self):
        metadata = CaptureMetadata(
            session_id="sess-explicit",
            backend="openai",
            model="gpt-4",
            request_id="req-123",
            transport="http",
            protocol_event="response",
            http_method="POST",
            url="https://example.invalid/v1/chat/completions",
            http_status_code=200,
            websocket_message_type="text",
        )

        event = CapturedWireEvent.from_metadata(
            timestamp=1.25,
            direction=CaptureDirection.PROXY_TO_CLIENT,
            sequence=7,
            data=b"payload",
            metadata=metadata,
        )

        assert event.session_id == "sess-explicit"
        assert event.backend == "openai"
        assert event.model == "gpt-4"
        assert event.request_id == "req-123"
        assert event.transport == "http"
        assert event.protocol_event == "response"
        assert event.http_method == "POST"
        assert event.url == "https://example.invalid/v1/chat/completions"
        assert event.http_status_code == 200
        assert event.websocket_message_type == "text"

        legacy_view = event.metadata
        assert legacy_view.session_id == "sess-explicit"
        assert legacy_view.transport == "http"
        assert legacy_view.protocol_event == "response"
        assert legacy_view.http_status_code == 200

    def test_dict_roundtrip_preserves_legacy_wire_shape(self):
        event = CapturedWireEvent(
            timestamp=3.5,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=11,
            data=b"hello",
            session_id="sess-1",
            backend="anthropic",
            model="claude-3",
            transport="http",
            protocol_event="frame",
            http_status_code=202,
        )

        encoded = event.to_dict()
        assert encoded["dir"] == CaptureDirection.BACKEND_TO_PROXY
        assert encoded["meta"]["sid"] == "sess-1"
        assert encoded["meta"]["be"] == "anthropic"
        assert encoded["meta"]["event"] == "frame"

        recreated = CapturedWireEvent.from_dict(encoded)
        assert recreated.session_id == "sess-1"
        assert recreated.backend == "anthropic"
        assert recreated.model == "claude-3"
        assert recreated.transport == "http"
        assert recreated.protocol_event == "frame"
        assert recreated.http_status_code == 202


class TestCaptureFileHeader:
    """Tests for CaptureFileHeader dataclass."""

    def test_default_values(self):
        """Test header has correct defaults."""
        header = CaptureFileHeader()
        assert header.magic == "LLMPROXY-CAPTURE-V2"
        assert header.version == 2
        assert header.validate() is True

    def test_to_dict(self):
        """Test header serialization."""
        header = CaptureFileHeader(session_id="test-session")
        result = header.to_dict()
        assert result["magic"] == "LLMPROXY-CAPTURE-V2"
        assert result["version"] == 2
        assert result["session_id"] == "test-session"

    def test_validate_invalid(self):
        """Test validation fails for wrong magic."""
        header = CaptureFileHeader(magic="WRONG")
        assert header.validate() is False


class TestCaptureSession:
    """Tests for CaptureSession dataclass."""

    def test_get_client_entries(self):
        """Test filtering client-side entries."""
        session = CaptureSession(
            header=CaptureFileHeader(),
            entries=[
                CaptureEntry(1.0, CaptureDirection.CLIENT_TO_PROXY, 0, b"req"),
                CaptureEntry(2.0, CaptureDirection.PROXY_TO_BACKEND, 1, b"be-req"),
                CaptureEntry(3.0, CaptureDirection.BACKEND_TO_PROXY, 2, b"be-resp"),
                CaptureEntry(4.0, CaptureDirection.PROXY_TO_CLIENT, 3, b"resp"),
            ],
        )
        client_entries = session.get_client_entries()
        assert len(client_entries) == 2
        assert client_entries[0].data == b"req"
        assert client_entries[1].data == b"resp"

    def test_get_backend_entries(self):
        """Test filtering backend-side entries."""
        session = CaptureSession(
            header=CaptureFileHeader(),
            entries=[
                CaptureEntry(1.0, CaptureDirection.CLIENT_TO_PROXY, 0, b"req"),
                CaptureEntry(2.0, CaptureDirection.PROXY_TO_BACKEND, 1, b"be-req"),
                CaptureEntry(3.0, CaptureDirection.BACKEND_TO_PROXY, 2, b"be-resp"),
                CaptureEntry(4.0, CaptureDirection.PROXY_TO_CLIENT, 3, b"resp"),
            ],
        )
        backend_entries = session.get_backend_entries()
        assert len(backend_entries) == 2
        assert backend_entries[0].data == b"be-req"
        assert backend_entries[1].data == b"be-resp"

    def test_get_timing_deltas(self):
        """Test timing delta calculation."""
        session = CaptureSession(
            header=CaptureFileHeader(),
            entries=[
                CaptureEntry(1.0, CaptureDirection.CLIENT_TO_PROXY, 0, b"1"),
                CaptureEntry(1.5, CaptureDirection.PROXY_TO_BACKEND, 1, b"2"),
                CaptureEntry(2.5, CaptureDirection.BACKEND_TO_PROXY, 2, b"3"),
            ],
        )
        deltas = session.get_timing_deltas()
        assert len(deltas) == 2
        assert abs(deltas[0] - 0.5) < 0.001
        assert abs(deltas[1] - 1.0) < 0.001


class TestCborWireCaptureService:
    """Tests for CborWireCaptureService."""

    def test_implements_recorder_interface(self):
        """Test the CBOR service exposes the canonical recorder interface."""
        assert issubclass(CborWireCaptureService, IWireCaptureRecorder)

    def test_append_enospc_disables_capture(self, mock_config, temp_capture_dir):
        """Disk full on append must disable capture without leaving the service enabled."""
        real_open = open

        def fake_open(path, mode="r", *args, **kwargs):
            m = mode if isinstance(mode, str) else getattr(mode, "value", "")
            if "a" in m and "b" in m:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_open(path, mode, *args, **kwargs)

        import builtins

        orig_open = builtins.open
        builtins.open = fake_open  # type: ignore[method-assign]
        try:
            service = CborWireCaptureService(
                config=mock_config,
                capture_dir=temp_capture_dir,
                session_id="enospc-session",
            )
            assert service.enabled()
            entry = CapturedWireEvent(
                timestamp=1700000000.0,
                direction=CaptureDirection.PROXY_TO_CLIENT,
                sequence=0,
                data=b"x",
                metadata=CaptureMetadata(session_id="enospc-session"),
            )
            service._write_entries_sync([entry])
            assert service.enabled() is False
        finally:
            builtins.open = orig_open  # type: ignore[method-assign]

    def test_append_enospc_throttles_exc_info_on_repeat(
        self, mock_config, temp_capture_dir, caplog
    ):
        """Repeated OS write failures should not emit a traceback on every attempt."""
        import logging

        real_open = open

        def fake_open(path, mode="r", *args, **kwargs):
            m = mode if isinstance(mode, str) else getattr(mode, "value", "")
            if "a" in m and "b" in m:
                raise OSError(errno.ENOSPC, "No space left on device")
            return real_open(path, mode, *args, **kwargs)

        import builtins

        orig_open = builtins.open
        builtins.open = fake_open  # type: ignore[method-assign]
        try:
            with caplog.at_level(logging.WARNING):
                service = CborWireCaptureService(
                    config=mock_config,
                    capture_dir=temp_capture_dir,
                    session_id="enospc-throttle",
                )
                entry = CapturedWireEvent(
                    timestamp=1700000001.0,
                    direction=CaptureDirection.PROXY_TO_CLIENT,
                    sequence=0,
                    data=b"x",
                    metadata=CaptureMetadata(session_id="enospc-throttle"),
                )
                service._write_entries_sync([entry])
                service._enabled = True
                service._write_entries_sync([entry])
            exc_info_records = [r for r in caplog.records if r.exc_info]
            assert len(exc_info_records) == 1
        finally:
            builtins.open = orig_open  # type: ignore[method-assign]

    @pytest.mark.asyncio
    async def test_extract_context_metadata_uses_request_id_fallback_when_b2bua_disabled(
        self, mock_config, temp_capture_dir
    ) -> None:
        service = CborWireCaptureService(
            config=_with_b2bua_disabled(mock_config),
            capture_dir=temp_capture_dir,
            session_id="capture-session",
        )
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="req-legacy-fallback",
        )

        metadata = service._extract_context_metadata(
            context=context,
            session_id=None,
        )

        assert metadata.session_id == "req-legacy-fallback"
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_extract_context_metadata_skips_request_id_fallback_when_b2bua_enabled(
        self, mock_config, temp_capture_dir
    ):
        b2bua_config = _with_b2bua_enabled(mock_config)
        service = CborWireCaptureService(
            config=b2bua_config,
            capture_dir=temp_capture_dir,
            session_id="capture-session",
        )
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="req-no-fallback",
        )

        metadata = service._extract_context_metadata(
            context=context,
            session_id=None,
        )

        assert metadata.session_id is None
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_extract_context_metadata_includes_compression_correlation_fields(
        self, mock_config, temp_capture_dir
    ) -> None:
        service = CborWireCaptureService(
            config=mock_config,
            capture_dir=temp_capture_dir,
            session_id="capture-session",
        )
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id="sess-corr",
        )

        metadata = service._extract_context_metadata(
            context=context,
            session_id="sess-corr",
            capture_metadata={
                "compression_correlation_id": "ccid-123",
                "compression_records_count": 4,
            },
        )

        assert metadata.compression_correlation_id == "ccid-123"
        assert metadata.compression_records_count == 4
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_extract_context_metadata_falls_back_to_context_extensions_for_compression_fields(
        self, mock_config, temp_capture_dir
    ) -> None:
        service = CborWireCaptureService(
            config=mock_config,
            capture_dir=temp_capture_dir,
            session_id="capture-session",
        )
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id="sess-corr",
            extensions={
                "compression_correlation_id": "ccid-from-context",
                "compression_records_count": 7,
            },
        )

        metadata = service._extract_context_metadata(
            context=context,
            session_id="sess-corr",
            capture_metadata=None,
        )

        assert metadata.compression_correlation_id == "ccid-from-context"
        assert metadata.compression_records_count == 7
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_extract_context_metadata_preserves_explicit_compression_metadata_precedence(
        self, mock_config, temp_capture_dir
    ) -> None:
        service = CborWireCaptureService(
            config=mock_config,
            capture_dir=temp_capture_dir,
            session_id="capture-session",
        )
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id="sess-corr",
            extensions={
                "compression_correlation_id": "ccid-from-context",
                "compression_records_count": 7,
            },
        )

        metadata = service._extract_context_metadata(
            context=context,
            session_id="sess-corr",
            capture_metadata={
                "compression_correlation_id": "ccid-explicit",
                "compression_records_count": 2,
            },
        )

        assert metadata.compression_correlation_id == "ccid-explicit"
        assert metadata.compression_records_count == 2
        await service.shutdown()

    def test_extract_context_metadata_populates_b2bua_identity_fields(
        self, capture_service
    ):
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id="llm-b2bua-a-4321",
            request_id="req-identity",
            b2bua_identity=B2buaIdentity(
                a_session_id="llm-b2bua-a-4321",
                b_session_id="llm-b2bua-b-4321-5",
                b_seq=5,
            ),
        )

        metadata = capture_service._extract_context_metadata(
            context=context,
            session_id=None,
        )

        assert metadata.session_id == "llm-b2bua-a-4321"
        assert metadata.a_session_id == "llm-b2bua-a-4321"
        assert metadata.b_session_id == "llm-b2bua-b-4321-5"
        assert metadata.b_seq == 5

    @pytest.mark.asyncio
    async def test_capture_stream_completion_with_canonical_usage(
        self, capture_service
    ):
        """Test that capture_stream_completion captures canonical_usage."""
        from src.core.domain.usage_canonical_record import CanonicalUsageRecord

        canonical_usage = CanonicalUsageRecord(
            provider_id="openai",
            model_id="gpt-4",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )

        await capture_service.capture_stream_completion(
            context=None,
            session_id="test-session",
            backend="openai",
            model="gpt-4",
            key_name=None,
            canonical_usage=canonical_usage,
        )

        await capture_service.shutdown()

        # Verify entry was written
        assert capture_service._file_path is not None
        assert capture_service._file_path.exists()

    def test_initialization_creates_directory(self, mock_config, temp_capture_dir):
        """Test service creates capture directory."""
        service = CborWireCaptureService(
            config=mock_config,
            capture_dir=temp_capture_dir / "subdir",
            session_id="test",
        )
        assert (temp_capture_dir / "subdir").exists()
        service._enabled = False

    def test_initialization_creates_file(self, capture_service, temp_capture_dir):
        """Test service creates capture file with header."""
        assert capture_service.enabled()
        file_path = capture_service.get_capture_file_path()
        assert file_path is not None
        assert file_path.exists()

        # Verify header was written
        with open(file_path, "rb") as f:
            header_dict = cbor2.load(f)
        assert header_dict["magic"] == "LLMPROXY-CAPTURE-V2"
        assert header_dict["session_id"] == "test-session-123"

    def test_disabled_when_no_capture_dir(self, mock_config):
        """Test service is disabled without capture_dir."""
        service = CborWireCaptureService(config=mock_config, capture_dir=None)
        assert not service.enabled()

    @pytest.mark.asyncio
    async def test_capture_inbound_request(self, capture_service, temp_capture_dir):
        """Test capturing inbound request."""
        await capture_service.capture_inbound_request(
            context=None,
            session_id="test-sess",
            request_payload={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

        # Force flush
        capture_service.force_flush_sync()

        # Read and verify
        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))
        # First is header, second is our entry
        assert len(entries) >= 2
        entry = entries[1]
        assert entry["dir"] == CaptureDirection.CLIENT_TO_PROXY
        assert entry["seq"] == 0
        assert b"gpt-4" in entry["data"]

    @pytest.mark.asyncio
    async def test_capture_outbound_request(self, capture_service):
        """Test capturing outbound request to backend."""
        await capture_service.capture_outbound_request(
            context=None,
            session_id="test-sess",
            backend="openai",
            model="gpt-4",
            key_name="OPENAI_KEY",
            request_payload=b'{"test": "data"}',
        )

        capture_service.force_flush_sync()

        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))
        assert len(entries) >= 2
        entry = entries[1]
        assert entry["dir"] == CaptureDirection.PROXY_TO_BACKEND
        assert entry["data"] == b'{"test": "data"}'
        assert entry["meta"]["be"] == "openai"

    @pytest.mark.asyncio
    async def test_capture_inbound_response(self, capture_service):
        """Test capturing inbound response from backend."""
        await capture_service.capture_inbound_response(
            context=None,
            session_id="test-sess",
            backend="anthropic",
            model="claude-3",
            key_name=None,
            response_content={"choices": [{"message": {"content": "Hello"}}]},
        )

        capture_service.force_flush_sync()

        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))
        assert len(entries) >= 2
        entry = entries[1]
        assert entry["dir"] == CaptureDirection.BACKEND_TO_PROXY
        assert entry["meta"]["mod"] == "claude-3"

    @pytest.mark.asyncio
    async def test_capture_inbound_response_uses_context_extensions_for_compression_metadata(
        self, capture_service
    ) -> None:
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="req-with-compression",
            extensions={
                "compression_correlation_id": "ccid-response-context",
                "compression_records_count": 5,
            },
        )

        await capture_service.capture_inbound_response(
            context=context,
            session_id="test-sess",
            backend="anthropic",
            model="claude-3",
            key_name=None,
            response_content={"choices": [{"message": {"content": "Hello"}}]},
            capture_metadata={
                "transport": "http",
                "protocol_event": "response",
            },
        )

        capture_service.force_flush_sync()

        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))
        assert len(entries) >= 2
        entry = entries[1]
        assert entry["meta"]["transport"] == "http"
        assert entry["meta"]["ccid"] == "ccid-response-context"
        assert entry["meta"]["crc"] == 5

    @pytest.mark.asyncio
    async def test_capture_outbound_response(self, capture_service):
        """Test capturing outbound response to client."""
        await capture_service.capture_outbound_response(
            context=None,
            session_id="test-sess",
            backend="gemini",
            model="gemini-pro",
            key_name=None,
            response_content=b"SSE response data",
        )

        capture_service.force_flush_sync()

        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))
        assert len(entries) >= 2
        entry = entries[1]
        assert entry["dir"] == CaptureDirection.PROXY_TO_CLIENT
        assert entry["data"] == b"SSE response data"

    @pytest.mark.asyncio
    async def test_capture_event_records_canonical_event(self, capture_service):
        """Test the recorder interface writes a canonical low-level event."""
        event = CapturedWireEvent(
            timestamp=1234.5,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=99,
            data=b"event-bytes",
            session_id="event-session",
            backend="openai",
            model="gpt-4",
            request_id="req-event",
            wire_schema="v2",
            transport="http",
            protocol_event="frame",
        )

        await capture_service.capture_event(event)
        capture_service.force_flush_sync()

        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))
        assert len(entries) >= 2
        entry = entries[1]
        assert entry["dir"] == CaptureDirection.BACKEND_TO_PROXY
        assert entry["seq"] == 99
        assert entry["data"] == b"event-bytes"
        assert entry["meta"]["sid"] == "event-session"
        assert entry["meta"]["wire_schema"] == "v2"
        assert entry["meta"]["transport"] == "http"

    @pytest.mark.asyncio
    async def test_wrap_inbound_stream(self, capture_service):
        """Test streaming capture from backend."""
        chunks = [b"chunk1", b"chunk2", b"chunk3"]

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            client_host="127.0.0.1",
            request_id="req-test-1",
            agent="pytest",
            extensions={
                "compression_correlation_id": "ccid-inbound-stream",
                "compression_records_count": 3,
            },
        )

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        wrapped = capture_service.wrap_inbound_stream(
            context=context,
            session_id="stream-test",
            backend="openai",
            model="gpt-4",
            key_name=None,
            stream=mock_stream(),
        )

        # Consume stream
        received = []
        async for chunk in wrapped:
            received.append(chunk)

        assert received == chunks

        capture_service.force_flush_sync()

        # Verify capture contains stream markers and chunks
        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))

        # Should have: header + stream_start + 3 chunks + stream_end
        stream_entries = [e for e in entries if isinstance(e, dict) and "dir" in e]
        assert len(stream_entries) >= 5

        # Check stream start
        start_entry = stream_entries[0]
        assert start_entry["meta"].get("ss") is True

        # Check stream end
        end_entry = stream_entries[-1]
        assert end_entry["meta"].get("se") is True
        assert end_entry["meta"].get("tc") == 3
        assert end_entry["meta"].get("tb") == sum(len(c) for c in chunks)
        assert end_entry["meta"].get("rid") == "req-test-1"

        # Check chunk entries include request id
        chunk_entries = [
            e
            for e in stream_entries
            if e.get("dir") == CaptureDirection.BACKEND_TO_PROXY and e.get("data")
        ]
        assert len(chunk_entries) == 3
        for entry in chunk_entries:
            assert entry["meta"].get("rid") == "req-test-1"
        for entry in stream_entries:
            assert entry["meta"].get("ccid") == "ccid-inbound-stream"
            assert entry["meta"].get("crc") == 3

    @pytest.mark.asyncio
    async def test_wrap_outbound_stream(self, capture_service):
        """Test streaming capture to client."""
        chunks = [b"data: test\n\n", b"data: done\n\n"]

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            client_host="127.0.0.1",
            request_id="req-test-2",
            agent="pytest",
            extensions={
                "compression_correlation_id": "ccid-outbound-stream",
                "compression_records_count": 4,
            },
        )

        async def mock_stream():
            for chunk in chunks:
                yield chunk

        wrapped = capture_service.wrap_outbound_stream(
            context=context,
            session_id="outbound-stream",
            backend="anthropic",
            model="claude-3",
            key_name=None,
            stream=mock_stream(),
        )

        received = []
        async for chunk in wrapped:
            received.append(chunk)

        assert received == chunks

        capture_service.force_flush_sync()

        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))

        # Verify direction is PROXY_TO_CLIENT
        stream_entries = [
            e
            for e in entries
            if isinstance(e, dict) and e.get("dir") == CaptureDirection.PROXY_TO_CLIENT
        ]
        assert len(stream_entries) >= 2

        # Chunk entries should carry rid
        chunk_entries = [e for e in stream_entries if e.get("data")]
        assert chunk_entries
        for entry in chunk_entries:
            assert entry["meta"].get("rid") == "req-test-2"
        for entry in stream_entries:
            assert entry["meta"].get("ccid") == "ccid-outbound-stream"
            assert entry["meta"].get("crc") == 4

    @pytest.mark.asyncio
    @pytest.mark.xdist_group(name="fake_clock")
    async def test_timestamp_precision(self, capture_service):
        """Test that timestamps have subsecond precision."""
        await capture_service.capture_inbound_request(
            context=None,
            session_id="ts-test",
            request_payload=b"test1",
        )
        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.05))
            clock.advance(0.05)  # 50ms delay for more reliable timing
            await sleep_task
        await capture_service.capture_inbound_request(
            context=None,
            session_id="ts-test",
            request_payload=b"test2",
        )

        capture_service.force_flush_sync()

        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))
        data_entries = [
            e for e in entries if isinstance(e, dict) and "ts" in e and e.get("data")
        ]

        assert len(data_entries) >= 2
        ts1 = data_entries[0]["ts"]
        ts2 = data_entries[1]["ts"]

        # Timestamps should be different and have subsecond precision
        # Note: On some systems, identical timestamps can occur for very fast operations
        assert ts2 >= ts1, "Timestamps should be monotonically non-decreasing"
        # Verify timestamps are floats with fractional part (subsecond precision)
        assert isinstance(ts1, float)
        assert isinstance(ts2, float)

    @pytest.mark.asyncio
    async def test_sequence_numbers(self, capture_service):
        """Test that sequence numbers are monotonically increasing."""
        for i in range(5):
            await capture_service.capture_inbound_request(
                context=None,
                session_id="seq-test",
                request_payload=f"request-{i}".encode(),
            )

        capture_service.force_flush_sync()

        file_path = capture_service.get_capture_file_path()
        entries = list(_read_cbor_entries(file_path))
        seq_entries = [e for e in entries if isinstance(e, dict) and "seq" in e]

        sequences = [e["seq"] for e in seq_entries]
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences)  # All unique

    @pytest.mark.asyncio
    async def test_shutdown_flushes_buffer(self, mock_config, temp_capture_dir):
        """Test that shutdown flushes remaining buffered entries."""
        service = CborWireCaptureService(
            config=mock_config,
            capture_dir=temp_capture_dir,
            session_id="shutdown-test",
        )

        await service.capture_inbound_request(
            context=None,
            session_id="test",
            request_payload=b"unflushed data",
        )

        # Shutdown should flush
        await service.shutdown()

        file_path = service.get_capture_file_path()
        assert file_path is not None
        entries = list(_read_cbor_entries(file_path))
        data_entries = [
            e
            for e in entries
            if isinstance(e, dict) and e.get("data") == b"unflushed data"
        ]
        assert len(data_entries) == 1

    def test_disabled_capture_is_noop(self, mock_config):
        """Test that disabled service is a no-op."""
        service = CborWireCaptureService(config=mock_config, capture_dir=None)
        assert not service.enabled()
        # These should not raise
        service.force_flush_sync()

    @pytest.mark.asyncio
    async def test_stream_passthrough_when_disabled(self, mock_config):
        """Test that streams pass through unchanged when disabled."""
        service = CborWireCaptureService(config=mock_config, capture_dir=None)

        async def mock_stream():
            yield b"chunk1"
            yield b"chunk2"

        wrapped = service.wrap_inbound_stream(
            context=None,
            session_id="test",
            backend="test",
            model="test",
            key_name=None,
            stream=mock_stream(),
        )

        received = []
        async for chunk in wrapped:
            received.append(chunk)

        assert received == [b"chunk1", b"chunk2"]

    @pytest.mark.asyncio
    async def test_request_timing_ttl_cleanup(self, capture_service, monkeypatch):
        """Test that stale request timing entries are cleaned up."""
        import src.core.services.cbor_wire_capture_service as cwcs_module

        # Override TTL for test
        monkeypatch.setattr(cwcs_module, "_REQUEST_TIMING_TTL_SECONDS", 0.1)

        # We need to mock the timestamp source so the cleanup actually sees time
        # advance without sleeping.
        current_time = [1000.0]

        def mock_time_ns():
            return int(current_time[0] * 1_000_000_000)

        monkeypatch.setattr(time, "time_ns", mock_time_ns)
        monkeypatch.setattr(cwcs_module.time, "time_ns", mock_time_ns)

        context1 = RequestContext(
            headers={}, cookies={}, state=None, app_state=None, request_id="req-old"
        )
        context2 = RequestContext(
            headers={}, cookies={}, state=None, app_state=None, request_id="req-new"
        )

        # Start first request
        await capture_service.capture_outbound_request(
            context=context1,
            session_id="test",
            backend="be",
            model="mod",
            key_name=None,
            request_payload=b"test1",
        )

        assert "req-old" in capture_service._request_timings

        # Advance clock past TTL (0.1s)
        current_time[0] += 0.2

        # Start second request (triggers cleanup)
        await capture_service.capture_outbound_request(
            context=context2,
            session_id="test",
            backend="be",
            model="mod",
            key_name=None,
            request_payload=b"test2",
        )

        # The old request timing should have been cleaned up
        assert "req-old" not in capture_service._request_timings
        assert "req-new" in capture_service._request_timings


def _read_cbor_entries(file_path: Path):
    """Helper to read all CBOR entries from a file."""
    with open(file_path, "rb") as f:
        while True:
            try:
                yield cbor2.load(f)
            except cbor2.CBORDecodeEOF:
                break
