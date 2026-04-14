"""Non-streaming ResponseExecutor execution tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from src.connectors.openai_codex.executor import ResponseExecutor
from src.connectors.openai_codex.interfaces import (
    ICompatibilityLayer,
    IResponseExecutor,
)
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import AuthenticationError, ServiceUnavailableError
from src.core.domain.responses import ResponseEnvelope


class TestResponseExecutor:
    """Test ResponseExecutor service implementation."""

    def test_executor_implements_interface(self, executor):
        """Verify executor implements IResponseExecutor interface."""
        assert isinstance(executor, IResponseExecutor)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_success(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test successful non-streaming execution."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "model": "gpt-5.1-codex",
            "choices": [{"message": {"role": "assistant", "content": "Response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        mock_response.headers = {"x-request-id": "req-123"}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "Response"}
        domain_response.usage = {"prompt_tokens": 10, "completion_tokens": 20}
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200
        assert result.usage == domain_response.usage
        assert result.metadata is not None
        assert result.metadata["backend"] == "openai-codex"
        assert result.metadata["model"] == sample_context.effective_model
        assert result.metadata["session_id"] == sample_context.session_id

    @pytest.mark.asyncio
    async def test_execute_non_streaming_usage_metadata(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test that usage metadata is extracted correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "choices": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200},
        }
        mock_response.headers = {}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = {"prompt_tokens": 100, "completion_tokens": 200}
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert result.usage == domain_response.usage

    @pytest.mark.asyncio
    async def test_execute_non_streaming_capture_metadata(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test that capture metadata is included in response envelope."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "chatcmpl-123", "choices": []}
        mock_response.headers = {"x-request-id": "req-456"}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert result.headers == {"x-request-id": "req-456"}
        assert result.metadata["backend"] == "openai-codex"

    @pytest.mark.asyncio
    async def test_execute_non_streaming_http_error(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test error mapping for HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": {"message": "Bad request"}}
        mock_response.text = '{"error": {"message": "Bad request"}}'
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(HTTPException) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_execute_non_streaming_network_error(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test error mapping for network errors."""
        mock_base_connector.client.post = AsyncMock(
            side_effect=httpx.RequestError("Network error")
        )

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert "Could not connect to backend" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_no_auth(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test error when no auth credentials found."""
        mock_base_connector.get_headers.return_value = {}

        with pytest.raises(AuthenticationError) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert "No auth credentials found" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_timeout_error(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test timeout errors map to ServiceUnavailableError."""
        import httpx

        mock_base_connector.client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out", request=MagicMock())
        )

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert "Could not connect to backend" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_invalid_response_format(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test invalid response format handling."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "Invalid response"
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        # Should raise an error when response can't be parsed
        with pytest.raises(ValueError):
            await executor.execute(non_streaming_payload, sample_context)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_usage_missing(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test handling when usage metadata is missing from response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "choices": [{"message": {"content": "test"}}],
            # No usage field
        }
        mock_response.headers = {}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = None  # No usage
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert result.usage is None

    @pytest.mark.asyncio
    async def test_execute_non_streaming_usage_unexpected_structure(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test handling when usage metadata has unexpected structure."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "choices": [],
        }
        mock_response.headers = {}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        # Usage with unexpected structure
        domain_response.usage = {"unexpected": "structure"}
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        # Should preserve usage as-is (translation service handles structure)
        assert result.usage == {"unexpected": "structure"}

    @pytest.mark.asyncio
    async def test_execute_non_streaming_retries_incompatible_tool_call(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Unsupported Codex tool calls should be swallowed and retried server-side."""
        compatibility_layer = MagicMock(spec=ICompatibilityLayer)
        compatibility_layer.detect_incompatible_tool_calls.return_value = [
            "apply_patch"
        ]
        compatibility_layer.append_incompatible_tool_steering.side_effect = (
            lambda payload_dict, incompatible_tools, context: {
                **payload_dict,
                "instructions": "retry steering",
            }
        )
        executor._compatibility_layer = compatibility_layer

        first_response = MagicMock()
        first_response.status_code = 200
        first_response.json.return_value = {
            "id": "resp-1",
            "output": [{"type": "function_call", "name": "apply_patch"}],
        }
        first_response.headers = {}

        second_response = MagicMock()
        second_response.status_code = 200
        second_response.json.return_value = {
            "id": "resp-2",
            "choices": [{"message": {"role": "assistant", "content": "final"}}],
        }
        second_response.headers = {}

        posted_payloads: list[dict[str, object]] = []

        async def post_side_effect(*args, **kwargs):
            posted_payloads.append(dict(kwargs["json"]))
            if len(posted_payloads) == 1:
                return first_response
            return second_response

        mock_base_connector.client.post = AsyncMock(side_effect=post_side_effect)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "final"}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, ResponseEnvelope)
        assert len(posted_payloads) == 2
        assert posted_payloads[1]["instructions"] == "retry steering"
        compatibility_layer.detect_incompatible_tool_calls.assert_called()
        compatibility_layer.append_incompatible_tool_steering.assert_called_once()
        mock_base_connector.translation_service.to_domain_response.assert_called_once_with(
            second_response.json.return_value, "openai-responses"
        )

    @pytest.mark.asyncio
    async def test_execute_non_streaming_retries_after_rate_limit_rotation(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """HTTP 429 should trigger managed-account rotation and retry."""
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {"Retry-After": "2"}
        rate_limited.json.return_value = {"error": {"message": "rate limited"}}
        rate_limited.text = '{"error": {"message": "rate limited"}}'

        success = MagicMock()
        success.status_code = 200
        success.headers = {}
        success.json.return_value = {
            "id": "chatcmpl-429-retry",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        }

        call_count = [0]

        async def post_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return rate_limited
            return success

        mock_base_connector.client.post = AsyncMock(side_effect=post_side_effect)
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "ok"}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, ResponseEnvelope)
        assert call_count[0] == 2
        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once_with(
            2.0,
            session_id=sample_context.session_id,
            upstream_codex_error={"error": {"message": "rate limited"}},
            response_headers=rate_limited.headers,
        )

    @pytest.mark.asyncio
    async def test_execute_non_streaming_uses_resets_in_seconds_from_usage_limit_json(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Codex usage_limit_reached JSON should supply retry delay via resets_in_seconds."""
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {}
        rate_limited.json.return_value = {
            "error": {
                "type": "usage_limit_reached",
                "message": "The usage limit has been reached",
                "plan_type": "plus",
                "resets_at": 1776358224,
                "resets_in_seconds": 191966,
            }
        }
        rate_limited.text = "{}"

        success = MagicMock()
        success.status_code = 200
        success.headers = {}
        success.json.return_value = {
            "id": "chatcmpl-429-codex-usage",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        }

        call_count = [0]

        async def post_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return rate_limited
            return success

        mock_base_connector.client.post = AsyncMock(side_effect=post_side_effect)
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "ok"}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, ResponseEnvelope)
        assert call_count[0] == 2
        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once_with(
            191966.0,
            session_id=sample_context.session_id,
            upstream_codex_error=rate_limited.json.return_value,
            response_headers=rate_limited.headers,
        )

    @pytest.mark.asyncio
    async def test_execute_non_streaming_429_usage_limit_notifies_when_rotation_exhausted(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        non_streaming_payload,
    ):
        """Final non-streaming 429 with Codex usage_limit must notify before HTTPException."""
        mock_credential_manager.effective_max_rate_limit_retries = AsyncMock(
            return_value=1
        )
        mock_credential_manager.notify_codex_usage_limit_unrecovered = AsyncMock()

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=2,
            retry_backoff_seconds=(0.01,),
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=False)

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {}
        usage_body = {
            "error": {
                "type": "usage_limit_reached",
                "message": "The usage limit has been reached",
                "plan_type": "plus",
                "resets_in_seconds": 3600,
            }
        }
        rate_limited.json.return_value = usage_body
        rate_limited.text = "{}"
        mock_base_connector.client.post = AsyncMock(return_value=rate_limited)

        with pytest.raises(HTTPException) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert exc_info.value.status_code == 429
        mock_credential_manager.notify_codex_usage_limit_unrecovered.assert_awaited_once()
        notify_kw = (
            mock_credential_manager.notify_codex_usage_limit_unrecovered.await_args.kwargs
        )
        assert notify_kw["upstream_detail"] == usage_body
        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_non_streaming_429_notifies_when_max_retries_zero(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        non_streaming_payload,
    ):
        """Non-streaming 429 with zero max_retries must still notify before raising."""
        mock_credential_manager.effective_max_rate_limit_retries = AsyncMock(
            return_value=0
        )
        mock_credential_manager.notify_codex_usage_limit_unrecovered = AsyncMock()

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=0,
            retry_backoff_seconds=(0.01,),
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=False)

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {}
        usage_body = {
            "error": {
                "type": "usage_limit_reached",
                "message": "The usage limit has been reached",
                "plan_type": "plus",
                "resets_in_seconds": 1800,
            }
        }
        rate_limited.json.return_value = usage_body
        rate_limited.text = "{}"
        mock_base_connector.client.post = AsyncMock(return_value=rate_limited)

        with pytest.raises(HTTPException) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert exc_info.value.status_code == 429
        mock_credential_manager.notify_codex_usage_limit_unrecovered.assert_awaited_once()
        mock_base_connector._handle_rate_limit_rotation.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_non_streaming_uses_payload_retry_after_when_header_missing(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Fallback retry_after extraction should use JSON payload when header absent."""
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.headers = {}
        rate_limited.json.return_value = {
            "error": {
                "message": "rate limited",
                "retry_after": 75,
            }
        }
        rate_limited.text = '{"error":{"message":"rate limited","retry_after":75}}'

        success = MagicMock()
        success.status_code = 200
        success.headers = {}
        success.json.return_value = {
            "id": "chatcmpl-429-payload-retry",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        }

        call_count = [0]

        async def post_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return rate_limited
            return success

        mock_base_connector.client.post = AsyncMock(side_effect=post_side_effect)
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "ok"}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, ResponseEnvelope)
        assert call_count[0] == 2
        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once_with(
            75.0,
            session_id=sample_context.session_id,
            upstream_codex_error={
                "error": {
                    "message": "rate limited",
                    "retry_after": 75,
                }
            },
            response_headers=rate_limited.headers,
        )

    @pytest.mark.asyncio
    async def test_execute_non_streaming_retries_for_forbidden_auth_error(
        self,
        executor,
        mock_base_connector,
        sample_context,
        non_streaming_payload,
    ):
        """HTTP 403 should prefer account-rotation over token refresh."""
        forbidden = MagicMock()
        forbidden.status_code = 403
        forbidden.headers = {}
        forbidden.json.return_value = {"error": {"message": "forbidden"}}
        forbidden.text = '{"error": {"message": "forbidden"}}'

        success = MagicMock()
        success.status_code = 200
        success.headers = {}
        success.json.return_value = {
            "id": "chatcmpl-403-retry",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        }

        call_count = [0]

        async def post_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return forbidden
            return success

        mock_base_connector.client.post = AsyncMock(side_effect=post_side_effect)
        mock_base_connector._handle_auth_failure_rotation = AsyncMock(return_value=True)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "ok"}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, ResponseEnvelope)
        assert call_count[0] == 2
        mock_base_connector._handle_auth_failure_rotation.assert_awaited_once_with(
            session_id=sample_context.session_id
        )

    async def test_execute_non_streaming_empty_choices_logs_trace(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test that empty choices are logged at TRACE level."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "model": "gpt-5.1-codex",
            "choices": [],
        }
        mock_response.headers = {}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        with patch("src.connectors.openai_codex.executor.logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            await executor.execute(non_streaming_payload, sample_context)

            mock_logger.log.assert_called()
            assert any(
                c.args and c.args[0] == TRACE_LEVEL
                for c in mock_logger.log.call_args_list
            )

    async def test_usage_format_compatibility_with_orchestrator(
        self, executor, non_streaming_payload, sample_context
    ):
        """Test that usage metadata format matches UsageAccountingOrchestrator expectations (Task 4.3, Req 8.1)."""
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

        # Verify usage is directly accessible via getattr (as used by orchestrator)
        usage = getattr(result, "usage", None)
        assert usage is not None
        assert isinstance(usage, UsageSummary)

        # Verify usage can be converted to dict via to_dict() (as expected by orchestrator)
        usage_dict = usage.to_dict()
        assert isinstance(usage_dict, dict)
        assert usage_dict["prompt_tokens"] == 10
        assert usage_dict["completion_tokens"] == 20
        assert usage_dict["total_tokens"] == 30

        # Verify usage can also be accessed via metadata fallback pattern
        # (orchestrator checks metadata.get("usage") if direct usage is None)
        if result.usage is None and result.metadata:
            metadata_usage = result.metadata.get("usage")
            # If present in metadata, it should be convertible to dict
            if metadata_usage is not None:
                if hasattr(metadata_usage, "to_dict"):
                    metadata_usage_dict = metadata_usage.to_dict()
                    assert isinstance(metadata_usage_dict, dict)
                elif isinstance(metadata_usage, dict):
                    assert isinstance(metadata_usage, dict)

    async def test_conversation_id_derived_from_prompt_cache_key(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test that conversation_id header is derived from prompt_cache_key (Req 1.2, 6.1)."""
        # Set prompt_cache_key in payload
        non_streaming_payload.prompt_cache_key = "test-conversation-key-123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "choices": [{"message": {"content": "Response"}}],
        }
        mock_response.headers = {}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        # Capture headers passed to client.post
        captured_headers = {}

        async def capture_headers(*args, **kwargs):
            if "headers" in kwargs:
                captured_headers.update(kwargs["headers"])
            return mock_response

        mock_base_connector.client.post = AsyncMock(side_effect=capture_headers)

        await executor.execute(non_streaming_payload, sample_context)

        # Verify conversation_id header matches prompt_cache_key
        assert "conversation_id" in captured_headers
        assert captured_headers["conversation_id"] == "test-conversation-key-123"
        # session_id should also be set (for logging/correlation)
        assert "session_id" in captured_headers
        assert captured_headers["session_id"] == "test-conversation-key-123"

    @pytest.mark.asyncio
    async def test_conversation_id_fallback_to_session_id_when_prompt_cache_key_missing(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test that conversation_id falls back to session_id when prompt_cache_key is missing (Req 1.2, 6.1)."""
        # Set prompt_cache_key to empty string
        non_streaming_payload.prompt_cache_key = ""

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "choices": [{"message": {"content": "Response"}}],
        }
        mock_response.headers = {}

        # Capture headers passed to client.post
        captured_headers = {}

        async def capture_headers(*args, **kwargs):
            if "headers" in kwargs:
                captured_headers.update(kwargs["headers"])
            return mock_response

        mock_base_connector.client.post = AsyncMock(side_effect=capture_headers)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        await executor.execute(non_streaming_payload, sample_context)

        # Verify conversation_id falls back to session_id
        assert "conversation_id" in captured_headers
        assert captured_headers["conversation_id"] == sample_context.session_id
        assert "session_id" in captured_headers
        assert captured_headers["session_id"] == sample_context.session_id
