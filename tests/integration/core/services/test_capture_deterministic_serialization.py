"""Integration tests for deterministic serialization and secret-safe logging.

Tests that capture services produce deterministic output and redact secrets.
Requirements: 7.3, NFR4.1, NFR4.2
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from src.core.common.contract_serialization import serialize_for_capture
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import (
    RequestContext,
    RequestCookies,
    RequestHeaders,
)
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.services.buffered_wire_capture_service import BufferedWireCapture
from src.core.services.cbor_wire_capture_service import CborWireCaptureService
from src.core.services.structured_wire_capture_service import StructuredWireCapture
from src.core.simulation.capture_reader import CaptureReader
from tests.unit.fixtures.markers import real_time


@pytest.fixture
def temp_capture_dir():
    """Create a temporary directory for capture files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    return AppConfig.from_env()


@pytest.fixture
def sample_request():
    """Create a sample canonical request for testing."""
    return CanonicalChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="Hello, world!"),
            ChatMessage(role="assistant", content="Hi there!"),
        ],
        temperature=0.7,
        max_tokens=100,
    )


@pytest.fixture
def sample_context():
    """Create a sample request context."""
    return RequestContext(
        headers=RequestHeaders(),
        cookies=RequestCookies(),
        state={},
        app_state={},
        request_id="test-request-123",
        session_id="test-session-456",
    )


@pytest.fixture
def sample_usage():
    """Create a sample usage record."""
    return CanonicalUsageRecord(
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
    )


class TestCborCaptureDeterministic:
    """Test CBOR capture produces deterministic output."""

    @pytest_asyncio.fixture  # pyright: ignore[reportUntypedFunctionDecorator]
    async def cbor_service(self, mock_config, temp_capture_dir):
        """Create a CBOR capture service."""
        service = CborWireCaptureService(
            config=mock_config,
            capture_dir=temp_capture_dir,
            session_id="test-session",
        )
        yield service
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_cbor_capture_deterministic(
        self, cbor_service, sample_request, sample_context
    ):
        """Same request produces identical CBOR capture entries."""
        # Capture the same request twice
        await cbor_service.capture_inbound_request(
            context=sample_context,
            session_id="test-session",
            request_payload=sample_request,
        )

        # Force flush to ensure data is written
        if hasattr(cbor_service, "force_flush_sync"):
            cbor_service.force_flush_sync()

        # Read the capture file
        capture_file = cbor_service.get_capture_file_path()
        assert capture_file.exists()

        # Read entries from file
        reader = CaptureReader()
        session1 = reader.load(capture_file)

        # Clear and capture again
        await cbor_service.shutdown()
        service2 = CborWireCaptureService(
            config=cbor_service._config,
            capture_dir=cbor_service._capture_dir,
            session_id="test-session",
        )

        await service2.capture_inbound_request(
            context=sample_context,
            session_id="test-session",
            request_payload=sample_request,
        )

        if hasattr(service2, "force_flush_sync"):
            service2.force_flush_sync()

        capture_file2 = service2.get_capture_file_path()
        assert capture_file2 is not None
        session2 = reader.load(capture_file2)

        # Compare data bytes - should be identical
        assert len(session1.entries) > 0
        assert len(session2.entries) > 0

        # Serialize both entries to compare
        entry1_data = session1.entries[0].data
        entry2_data = session2.entries[0].data

        # Data should be identical (deterministic serialization)
        assert entry1_data == entry2_data, "Capture entries should be identical"

        await service2.shutdown()

    @pytest.mark.asyncio
    async def test_cbor_capture_serialize_for_capture_deterministic(
        self, sample_request
    ):
        """serialize_for_capture produces identical output for same input."""
        # Serialize the same request multiple times
        result1 = serialize_for_capture(sample_request)
        result2 = serialize_for_capture(sample_request)
        result3 = serialize_for_capture(sample_request)

        # All should be identical
        assert result1 == result2 == result3
        assert isinstance(result1, bytes)

    @pytest.mark.asyncio
    async def test_cbor_capture_replay_compatibility(
        self, cbor_service, sample_request, sample_context, sample_usage
    ):
        """Deterministic serialization doesn't break replay tooling."""
        # Capture request and response
        await cbor_service.capture_inbound_request(
            context=sample_context,
            session_id="test-session",
            request_payload=sample_request,
        )

        await cbor_service.capture_inbound_response(
            context=sample_context,
            session_id="test-session",
            backend="openai",
            model="gpt-4",
            key_name=None,
            response_content={"content": "test response"},
            canonical_usage=sample_usage,
        )

        if hasattr(cbor_service, "force_flush_sync"):
            cbor_service.force_flush_sync()

        # Verify CaptureReader can load and decode
        capture_file = cbor_service.get_capture_file_path()
        reader = CaptureReader()
        session = reader.load(capture_file)

        assert session.header is not None
        assert len(session.entries) >= 2

        # Verify entries can be decoded
        for entry in session.entries:
            assert entry.data is not None or entry.metadata is not None
            assert entry.timestamp is not None


class _MockLoggingConfig:
    """Minimal stand-in for the project's logging configuration."""

    capture_file: str | None = None
    capture_max_bytes: int | None = None
    capture_truncate_bytes: int | None = None
    capture_max_files: int = 0
    capture_rotate_interval_seconds: int = 0
    capture_total_max_bytes: int = 0


class TestStructuredCaptureDeterministic:
    """Test structured (JSON) capture produces deterministic output."""

    @pytest.fixture
    def structured_service(self, mock_config, temp_capture_dir):
        """Create a structured capture service."""
        if not hasattr(mock_config, "logging"):
            mock_config.logging = _MockLoggingConfig()
        mock_config.logging.capture_file = str(temp_capture_dir / "structured.jsonl")

        service = StructuredWireCapture(config=mock_config)
        return service

    def test_structured_capture_deterministic(
        self, structured_service, sample_request, sample_context
    ):
        """Same request produces identical JSON capture entries (excluding timestamps)."""
        import asyncio

        async def _test():
            # Capture the same request
            await structured_service.capture_inbound_request(
                context=sample_context,
                session_id="test-session",
                request_payload=sample_request,
            )

            # Read the file
            capture_file = Path(structured_service._file_path)
            if capture_file.exists():
                with open(capture_file, encoding="utf-8") as f:
                    lines = f.readlines()

                assert len(lines) > 0

                # Parse JSON entries
                entry1 = json.loads(lines[0])

                # Capture again (clear file first)
                capture_file.unlink(missing_ok=True)

                await structured_service.capture_inbound_request(
                    context=sample_context,
                    session_id="test-session",
                    request_payload=sample_request,
                )

                with open(capture_file, encoding="utf-8") as f:
                    lines2 = f.readlines()

                entry2 = json.loads(lines2[0])

                # Remove timestamp fields for comparison (they will differ)
                entry1_no_time = {
                    k: v for k, v in entry1.items() if "timestamp" not in k.lower()
                }
                entry2_no_time = {
                    k: v for k, v in entry2.items() if "timestamp" not in k.lower()
                }

                # Compare JSON strings (should be identical due to sorted keys)
                json_str1 = json.dumps(entry1_no_time, sort_keys=True)
                json_str2 = json.dumps(entry2_no_time, sort_keys=True)

                # Payload and metadata should be identical (deterministic serialization)
                assert (
                    json_str1 == json_str2
                ), "JSON entries (excluding timestamps) should be identical"

        asyncio.run(_test())


class TestCaptureRedactsSecrets:
    """Test that capture files don't contain unredacted secrets."""

    @pytest_asyncio.fixture  # pyright: ignore[reportUntypedFunctionDecorator]
    async def cbor_service(self, mock_config, temp_capture_dir):
        """Create a CBOR capture service."""
        service = CborWireCaptureService(
            config=mock_config,
            capture_dir=temp_capture_dir,
            session_id="test-session",
        )
        yield service
        await service.shutdown()

    @pytest.mark.asyncio
    async def test_capture_redacts_secrets(self, cbor_service, sample_context):
        """Capture files don't contain unredacted secrets."""
        # Create a request with sensitive data
        sensitive_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "test"}],
            "api_key": "fake_api_key_for_testing",  # Should be redacted
            "password": "secret123",  # Should be redacted
            "normal_field": "value",  # Should be preserved
        }

        await cbor_service.capture_inbound_request(
            context=sample_context,
            session_id="test-session",
            request_payload=sensitive_request,
        )

        if hasattr(cbor_service, "force_flush_sync"):
            cbor_service.force_flush_sync()

        # Read capture file
        capture_file = cbor_service.get_capture_file_path()
        reader = CaptureReader()
        session = reader.load(capture_file)

        assert len(session.entries) > 0

        # Dict/list inbound payloads are stored as redacted deterministic JSON bytes.
        entry_data = session.entries[0].data
        text = entry_data.decode("utf-8")
        assert "fake_api_key_for_testing" not in text
        assert "secret123" not in text
        decoded = json.loads(text)
        assert decoded.get("normal_field") == "value"

    def test_serialize_for_logging_redacts_in_capture_context(self):
        """serialize_for_logging redacts secrets when used for capture metadata."""
        from src.core.common.contract_serialization import serialize_for_logging

        sensitive_data = {
            "api_key": "sk-test123456789",
            "password": "secret123",
            "model": "gpt-4",
        }

        # Serialize with redaction
        result = serialize_for_logging(sensitive_data, redact=True)
        parsed = json.loads(result)

        # Verify redaction
        assert parsed["api_key"] != "sk-test123456789"
        assert parsed["password"] != "secret123"
        assert parsed["model"] == "gpt-4"  # Non-sensitive preserved

        # Verify deterministic (same input produces same output)
        result2 = serialize_for_logging(sensitive_data, redact=True)
        assert result == result2


class TestLegacyWireCaptureDeterministic:
    """Tests for legacy WireCapture service deterministic serialization."""

    @pytest.mark.asyncio
    async def test_legacy_wire_capture_deterministic(self, tmp_path: Path) -> None:
        """Legacy WireCapture produces deterministic output for identical inputs."""
        from src.core.config.app_config import AppConfig
        from src.core.domain.request_context import RequestContext
        from src.core.services.wire_capture_service import WireCapture

        capture_file = tmp_path / "legacy_capture.txt"
        # WireCapture uses AppConfig, so we need to create a config with the capture file path
        config = AppConfig.from_env()
        # Set the capture file path on the config
        config.logging.capture_file = str(capture_file)
        service = WireCapture(config=config)

        # Create identical request payloads
        request_payload1 = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
        }
        request_payload2 = {
            "temperature": 0.7,
            "messages": [{"role": "user", "content": "Hello"}],
            "model": "gpt-4",
        }  # Same data, different key order

        # Create mock context
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state={},
        )

        # Capture first request
        await service.capture_inbound_request(
            context=context,
            session_id="test-session-1",
            request_payload=request_payload1,
        )

        # Capture second request (same data, different dict key order)
        await service.capture_inbound_request(
            context=context,
            session_id="test-session-1",
            request_payload=request_payload2,
        )

        # Read capture file
        content = capture_file.read_text(encoding="utf-8")

        # Legacy wire capture format: header lines followed by multi-line JSON payloads
        # Extract JSON payloads by finding blocks between headers
        import json
        import re

        # Split by header markers
        sections = re.split(r"----- INBOUND_REQUEST.*?-----\n", content)
        payload_lines = []

        for section in sections[1:]:  # Skip first empty section
            # Extract JSON from section (between header line and next header or end)
            lines = section.split("\n")
            # Skip the first line (client=unknown session=...)
            json_lines = []
            in_json = False
            for line in lines[1:]:  # Skip header line
                stripped = line.strip()
                if stripped.startswith("{"):
                    in_json = True
                if in_json:
                    json_lines.append(line)
                    if stripped.endswith("}") and stripped.count("{") == stripped.count(
                        "}"
                    ):
                        break

            if json_lines:
                json_str = "\n".join(json_lines)
                try:
                    payload = json.loads(json_str)
                    payload_lines.append(payload)
                except json.JSONDecodeError:
                    pass

        # Should have 2 payload entries
        assert (
            len(payload_lines) >= 2
        ), f"Expected at least 2 payload entries, got {len(payload_lines)}. Content:\n{content}"

        # Parse JSON payloads
        payload1 = payload_lines[0]
        payload2 = payload_lines[1]

        # Keys should be sorted deterministically (Requirement 7.3)
        # Both payloads should have identical key order despite different input order
        assert list(payload1.keys()) == list(payload2.keys())
        assert payload1 == payload2

        # Verify keys are sorted alphabetically
        keys = list(payload1.keys())
        assert keys == sorted(keys), "Keys should be sorted for deterministic output"


class TestBufferedCaptureDeterministic:
    """Test buffered capture produces deterministic output."""

    @pytest.fixture
    def buffered_service(self, mock_config):
        """Create a buffered capture service."""
        service = BufferedWireCapture(config=mock_config)
        return service

    @real_time(reason="Test validates deterministic serialization with real timestamps")
    def test_buffered_capture_deterministic_serialization(
        self, buffered_service, sample_request
    ):
        """Buffered capture uses deterministic serialization."""
        from datetime import datetime, timezone

        from src.core.services.buffered_wire_capture_service import WireCaptureEntry

        # Convert request to dict for payload (as the service normally does)
        payload_dict = (
            sample_request.model_dump()
            if hasattr(sample_request, "model_dump")
            else sample_request
        )

        # Create an entry with correct fields
        now = datetime.now(timezone.utc)
        entry = WireCaptureEntry(
            timestamp_iso=now.isoformat(),
            timestamp_unix=now.timestamp(),
            sequence=1,
            direction="inbound_request",
            source="client",
            destination="proxy",
            session_id="test-session",
            backend="openai",
            model="gpt-4",
            key_name=None,
            content_type="json",
            content_length=100,
            payload=payload_dict,
            metadata={},
        )

        # Serialize multiple times
        json1 = buffered_service._serialize_entry_cached(entry)
        json2 = buffered_service._serialize_entry_cached(entry)
        json3 = buffered_service._serialize_entry_cached(entry)

        # Should be identical (deterministic)
        assert json1 == json2 == json3

        # Parse and verify keys are sorted
        parsed = json.loads(json1)
        keys = list(parsed.keys())
        assert keys == sorted(keys), "Keys should be sorted for deterministic output"
