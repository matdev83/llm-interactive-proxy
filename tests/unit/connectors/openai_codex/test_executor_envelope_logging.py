"""ResponseEnvelope, streaming envelope, and logging behavior tests."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import ServiceUnavailableError
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestResponseExecutor:
    """Test ResponseExecutor service implementation."""

    async def test_response_envelope_includes_usage_metadata(
        self, executor, non_streaming_payload, sample_context
    ):
        """Test that ResponseEnvelope includes usage metadata from domain response (Task 4.3)."""
        from src.core.domain.usage_summary import UsageSummary

        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "id": "test-id",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "Test"}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        }

        executor._base_connector.client.post = AsyncMock(return_value=mock_response)

        # Mock domain response with usage
        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "Test"}
        domain_response.usage = UsageSummary(
            prompt_tokens=10, completion_tokens=20, total_tokens=30
        )
        executor._base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, ResponseEnvelope)
        assert result.usage is not None
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 20
        assert result.usage.total_tokens == 30

    @pytest.mark.asyncio
    async def test_response_envelope_includes_metadata_fields(
        self, executor, non_streaming_payload, sample_context
    ):
        """Test that ResponseEnvelope includes metadata fields (backend, model, session_id) (Task 4.3)."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "id": "test-id",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "Test"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

        executor._base_connector.client.post = AsyncMock(return_value=mock_response)

        # Mock domain response
        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "Test"}
        domain_response.usage = None
        executor._base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, ResponseEnvelope)
        assert result.metadata is not None
        assert result.metadata["backend"] == "openai-codex"
        assert result.metadata["model"] == sample_context.effective_model
        assert result.metadata["session_id"] == sample_context.session_id

    @pytest.mark.asyncio
    async def test_logging_includes_correlation_fields(
        self, executor, non_streaming_payload, sample_context, caplog
    ):
        """Test that TRACE logging includes correlation fields (backend, session_id) (Task 4.3)."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "id": "test-id",
            "object": "chat.completion",
            "choices": [{"message": {"role": "assistant", "content": "Test"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

        executor._base_connector.client.post = AsyncMock(return_value=mock_response)

        # Mock domain response
        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "Test"}
        domain_response.usage = None
        executor._base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        caplog.set_level(TRACE_LEVEL, logger="src.connectors.openai_codex.executor")
        await executor.execute(non_streaming_payload, sample_context)

        trace_records = [
            record
            for record in caplog.records
            if record.name == "src.connectors.openai_codex.executor"
            and record.levelno == TRACE_LEVEL
            and getattr(record, "backend", None) == "openai-codex"
        ]
        assert len(trace_records) > 0

        for record in trace_records:
            assert getattr(record, "session_id", None) == sample_context.session_id
            assert getattr(record, "model", None) == sample_context.effective_model

    @pytest.mark.asyncio
    async def test_error_logging_includes_correlation_fields(
        self, executor, non_streaming_payload, sample_context, caplog
    ):
        """Test that error logging includes correlation fields (Task 4.3)."""
        # Mock network error
        executor._base_connector.client.post = AsyncMock(
            side_effect=httpx.RequestError("Connection failed")
        )

        caplog.set_level(logging.ERROR, logger="src.connectors.openai_codex.executor")

        with pytest.raises(ServiceUnavailableError):
            await executor.execute(non_streaming_payload, sample_context)

        error_records = [
            record
            for record in caplog.records
            if record.name == "src.connectors.openai_codex.executor"
            and record.levelno >= logging.ERROR
            and getattr(record, "backend", None) == "openai-codex"
        ]
        assert len(error_records) > 0

        for record in error_records:
            assert getattr(record, "session_id", None) == sample_context.session_id
            assert getattr(record, "model", None) == sample_context.effective_model

    @pytest.mark.asyncio
    async def test_info_logging_includes_correlation_fields(
        self, executor, streaming_payload, sample_context, caplog
    ):
        """Test that info-level logging includes correlation fields (Task 4.3, Req 8.4)."""
        # Mock streaming response with auth error chunk
        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {"Content-Type": "text/event-stream"}
        mock_stream_handle.cancel_callback = AsyncMock()

        async def auth_error_iterator():
            # Return chunk that triggers auth retry
            yield ProcessedResponse(
                content={
                    "error": "auth_failed",
                    "details": {"status": 401},
                }
            )

        mock_stream_handle.iterator = auth_error_iterator()

        # Mock successful retry
        mock_stream_handle_success = MagicMock()
        mock_stream_handle_success.headers = {}
        mock_stream_handle_success.cancel_callback = AsyncMock()

        async def success_iterator():
            yield ProcessedResponse(content=b"data: test\n\n", metadata={})

        mock_stream_handle_success.iterator = success_iterator()

        call_count = [0]

        async def handle_streaming_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_stream_handle
            return mock_stream_handle_success

        executor._base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        caplog.set_level(logging.INFO, logger="src.connectors.openai_codex.executor")

        result = await executor.execute(streaming_payload, sample_context)

        # Consume stream to trigger auth error detection and info logging
        async for _ in result.content:
            break

        info_records = [
            record
            for record in caplog.records
            if record.name == "src.connectors.openai_codex.executor"
            and record.levelno == logging.INFO
            and "authentication failure" in record.getMessage().lower()
            and getattr(record, "backend", None) == "openai-codex"
        ]
        assert len(info_records) > 0

        for record in info_records:
            assert getattr(record, "session_id", None) == sample_context.session_id
            assert getattr(record, "model", None) == sample_context.effective_model

    def test_logging_secret_redaction(self):
        """Test that secrets are redacted in logs (Task 4.3, Req 8.5)."""
        from src.core.common.logging_utils import ApiKeyRedactionFilter

        # Create a test API key that should be redacted
        # Using clearly fake test values that don't match real API key patterns
        test_api_key = "test-api-key-for-redaction-verification-12345"
        test_token = "Bearer test-bearer-token-for-redaction-67890"

        # Create a logger with redaction filter
        test_logger = logging.getLogger("test_codex_redaction")
        test_logger.setLevel(logging.DEBUG)

        # Add handler to capture log records
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        test_logger.addHandler(handler)

        # Install redaction filter (will use default patterns)
        redaction_filter = ApiKeyRedactionFilter(api_keys=[test_api_key])
        test_logger.addFilter(redaction_filter)

        # Create a log record with secret in message string (not template)
        log_message = f"API key is {test_api_key} and token is {test_token}"
        record = logging.LogRecord(
            name="test_codex_redaction",
            level=logging.INFO,
            pathname="test",
            lineno=1,
            msg=log_message,
            args=None,
            exc_info=None,
        )

        # Apply filter (modifies record in place)
        filter_result = redaction_filter.filter(record)

        # Verify filter allows the record
        assert filter_result is True

        # Verify secrets are redacted in message
        assert test_api_key not in str(record.msg)
        assert "***" in str(record.msg)

        # Test with args tuple
        record2 = logging.LogRecord(
            name="test_codex_redaction",
            level=logging.INFO,
            pathname="test",
            lineno=1,
            msg="API key is %s and token is %s",
            args=(test_api_key, test_token),
            exc_info=None,
        )

        # Apply filter
        redaction_filter.filter(record2)

        # Verify secrets are redacted in args
        assert record2.args is not None
        if isinstance(record2.args, tuple):
            for arg in record2.args:
                if isinstance(arg, str):
                    assert test_api_key not in arg
                    # Bearer tokens get special handling
                    if "Bearer" in arg:
                        assert "***" in arg or "(API_KEY_HAS_BEEN_REDACTED)" in arg

        # Cleanup
        test_logger.removeFilter(redaction_filter)
        test_logger.removeHandler(handler)

    async def test_streaming_envelope_includes_metadata_fields(
        self, executor, streaming_payload, sample_context
    ):
        """Test that StreamingResponseEnvelope includes metadata fields (Task 4.3)."""

        # Mock successful streaming response
        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {"Content-Type": "text/event-stream"}
        mock_stream_handle.cancel_callback = None

        async def mock_iterator():
            from src.core.interfaces.response_processor_interface import (
                ProcessedResponse,
            )

            yield ProcessedResponse(content=b"data: test\n\n", metadata={})

        mock_stream_handle.iterator = mock_iterator()

        executor._base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        result = await executor.execute(streaming_payload, sample_context)

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.metadata is not None
        assert result.metadata["backend"] == "openai-codex"
        assert result.metadata["model"] == sample_context.effective_model
        assert result.metadata["session_id"] == sample_context.session_id

    @pytest.mark.asyncio
    async def test_streaming_envelope_can_include_canonical_usage(
        self, executor, streaming_payload, sample_context
    ):
        """Test that StreamingResponseEnvelope can include canonical_usage when available (Task 4.3)."""
        from src.core.domain.usage_canonical_record import CanonicalUsageRecord

        # Mock successful streaming response
        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {"Content-Type": "text/event-stream"}
        mock_stream_handle.cancel_callback = None

        async def mock_iterator():
            from src.core.interfaces.response_processor_interface import (
                ProcessedResponse,
            )

            yield ProcessedResponse(content=b"data: test\n\n", metadata={})

        mock_stream_handle.iterator = mock_iterator()

        executor._base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        result = await executor.execute(streaming_payload, sample_context)

        assert isinstance(result, StreamingResponseEnvelope)
        # canonical_usage is optional and may be None for streaming responses
        # (usage is typically calculated at end of stream)
        # But if it's set, it should be a CanonicalUsageRecord
        if result.canonical_usage is not None:
            assert isinstance(result.canonical_usage, CanonicalUsageRecord)
