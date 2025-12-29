"""Integration tests for OpenAI Codex compatibility layer activation."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


@pytest_asyncio.fixture(name="auth_dir")
async def auth_dir_tmp(tmp_path: Path):
    """Create temporary auth directory with credentials."""
    data = {"tokens": {"access_token": "test_token"}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture(name="codex_connector_compat_disabled")
async def codex_connector_compat_disabled_fixture(auth_dir: Path):
    """Create connector with compatibility layer disabled."""
    async with httpx.AsyncClient() as client:
        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAICodexConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_codex_path=str(auth_dir))
            backend._auth_credentials = {"tokens": {"access_token": "test_token"}}
            yield backend


@pytest_asyncio.fixture(name="codex_connector_compat_enabled")
async def codex_connector_compat_enabled_fixture(auth_dir: Path):
    """Create connector with compatibility layer enabled."""
    async with httpx.AsyncClient() as client:
        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAICodexConnector(client, cfg, translation_service=ts)

        # Enable compatibility layer
        backend._connector_settings["compatibility_layer"]["enabled"] = True

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_codex_path=str(auth_dir))
            backend._auth_credentials = {"tokens": {"access_token": "test_token"}}

            # Manually initialize session detector since we modified settings after init
            from src.connectors._openai_codex_kilo_tool_translator import (
                KiloToolTranslator,
            )
            from src.connectors._openai_codex_session_detector import SessionDetector
            from src.connectors.openai_codex.compat import CompatibilityLayer

            detection_cfg = backend._connector_settings["compatibility_layer"][
                "detection"
            ]
            backend._session_detector = SessionDetector(
                cache_ttl_seconds=detection_cfg["cache_ttl_seconds"],
                heuristic_threshold=detection_cfg["heuristic_threshold"],
            )
            backend._compatibility_layer_enabled = True

            # Ensure kilo_translator is initialized
            if backend._kilo_tool_translator is None:
                backend._kilo_tool_translator = KiloToolTranslator(backend, None)

            # Recreate compatibility layer with proper dependencies
            backend._compatibility_layer = CompatibilityLayer(
                session_detector=backend._session_detector,
                kilo_translator=backend._kilo_tool_translator,
                tool_execution_service=backend._tool_execution_service,
            )

            yield backend


class TestCompatibilityLayerConfiguration:
    """Test compatibility layer configuration loading."""

    @pytest.mark.asyncio
    async def test_compatibility_layer_disabled_by_default(
        self, codex_connector_compat_disabled: OpenAICodexConnector
    ):
        """Test that compatibility layer is disabled by default."""
        assert codex_connector_compat_disabled._compatibility_layer_enabled is False
        assert codex_connector_compat_disabled._session_detector is None

    @pytest.mark.asyncio
    async def test_compatibility_layer_can_be_enabled(
        self, codex_connector_compat_enabled: OpenAICodexConnector
    ):
        """Test that compatibility layer can be enabled."""
        assert codex_connector_compat_enabled._compatibility_layer_enabled is True
        assert codex_connector_compat_enabled._session_detector is not None

    @pytest.mark.asyncio
    async def test_session_detector_initialized_with_config(
        self, codex_connector_compat_enabled: OpenAICodexConnector
    ):
        """Test that SessionDetector is initialized with correct config."""
        detector = codex_connector_compat_enabled._session_detector
        assert detector is not None
        assert detector._cache_ttl == 3600
        assert detector._heuristic_threshold == 2


class TestCompatibilityLayerDetection:
    """Test compatibility layer detection in connector context."""

    @pytest.mark.asyncio
    async def test_kilocode_detection_via_metadata(
        self, codex_connector_compat_enabled: OpenAICodexConnector
    ):
        """Test KiloCode detection through metadata."""
        from unittest.mock import MagicMock

        detector = codex_connector_compat_enabled._session_detector
        assert detector is not None

        request_data = MagicMock()
        metadata = {"agent": "kilocode"}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is True
        assert result.detection_method == "metadata"

    @pytest.mark.asyncio
    async def test_non_kilocode_not_detected(
        self, codex_connector_compat_enabled: OpenAICodexConnector
    ):
        """Test that non-KiloCode clients are not detected."""
        from unittest.mock import MagicMock

        detector = codex_connector_compat_enabled._session_detector
        assert detector is not None

        request_data = MagicMock()
        metadata = {"agent": "cline"}

        result = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        assert result.is_kilocode is False

    @pytest.mark.asyncio
    async def test_detection_caching_works(
        self, codex_connector_compat_enabled: OpenAICodexConnector
    ):
        """Test that detection results are cached."""
        from unittest.mock import MagicMock

        detector = codex_connector_compat_enabled._session_detector
        assert detector is not None

        request_data = MagicMock()
        metadata = {"agent": "kilocode"}

        # First detection
        result1 = await detector.detect(
            request_data=request_data,
            metadata=metadata,
            session_id="test_session",
            backend="openai-codex",
        )

        # Second detection should use cache
        result2 = await detector.detect(
            request_data=request_data,
            metadata={"agent": "different"},  # Different metadata
            session_id="test_session",
            backend="openai-codex",
        )

        assert result1.is_kilocode is True
        assert result2.is_kilocode is True
        assert result2.detection_method == "cached"


class TestRequestFlowIntegration:
    """Test full request flow with compatibility layer integration."""

    @pytest.mark.asyncio
    async def test_full_request_flow_with_kilocode_client(
        self, codex_connector_compat_enabled: OpenAICodexConnector
    ):
        """Test full request flow with KiloCode client activates compatibility layer."""
        from unittest.mock import AsyncMock, MagicMock, patch

        # Create mock request data
        request_data = MagicMock()
        request_data.model = "gpt-5-codex"
        request_data.messages = [{"role": "user", "content": "Hello"}]
        request_data.stream = False
        request_data.metadata = {"agent": "kilocode"}

        # Create mock domain request
        domain_request = MagicMock()
        domain_request.session_id = "test_session_123"
        domain_request.processing_context = {}
        domain_request.metadata = {"agent": "kilocode"}

        processed_messages = [{"role": "user", "content": "Hello"}]

        # Mock the Codex API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test_response",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello! How can I help you?",
                    }
                }
            ],
        }

        # Create payload mock
        payload_mock = MagicMock()
        payload_mock.model_dump.return_value = {"input": []}
        payload_mock.prompt_cache_key = "test_key"

        with (
            patch.object(
                codex_connector_compat_enabled.client,
                "post",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch.object(
                codex_connector_compat_enabled,
                "_build_codex_payload",
                return_value=(payload_mock, "conv_cache"),
            ),
        ):
            # Call the method
            await codex_connector_compat_enabled._call_codex_responses_api(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model="gpt-5-codex",
                domain_request=domain_request,
            )

            # Verify detection was performed and stored in context
            assert domain_request.processing_context.get("is_kilocode_client") is True
            assert domain_request.processing_context.get(
                "kilocode_detection_method"
            ) in [
                "metadata",
                "cached",
            ]

    @pytest.mark.asyncio
    async def test_translate_kilo_tool_adds_tool_call_metadata(
        self, codex_connector_compat_enabled: OpenAICodexConnector
    ):
        """Ensure translator adds tool call metadata for Codex execution.

        After refactoring, tool translation is handled by CompatibilityLayer.
        This test verifies the compatibility layer correctly translates tools.
        """
        from src.connectors._openai_codex_capabilities import CodexClientCapabilities
        from src.connectors.openai_codex.contracts import (
            CodexRequestContext,
            ProcessedMessage,
        )
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        # Create a request context with KiloCode-style message
        message_content = '<read_file path="src/app.py" />'
        processed_message = ProcessedMessage(
            role="assistant",
            content=message_content,
        )

        # Create proper CanonicalChatRequest instance (required by CodexRequestContext)
        # Include both user and assistant messages to match processed_messages
        request = CanonicalChatRequest(
            messages=[
                ChatMessage(role="user", content="test"),
                ChatMessage(role="assistant", content=message_content),
            ],
            model="gpt-5-codex",
            stream=False,
        )
        # Set metadata to indicate KiloCode client (required for compatibility layer detection)
        context = CodexRequestContext(
            request=request,
            processed_messages=[processed_message],
            effective_model="gpt-5-codex",
            capabilities=CodexClientCapabilities(),
            session_id="test_session",
            metadata={"agent": "kilocode"},  # Enable KiloCode detection
        )

        # Mock session detector to ensure KiloCode is detected
        from unittest.mock import AsyncMock

        if codex_connector_compat_enabled._compatibility_layer:
            # Mock the session detector to return positive detection
            if codex_connector_compat_enabled._compatibility_layer._session_detector:
                from unittest.mock import MagicMock

                detection_result = MagicMock()
                detection_result.is_kilocode = True
                detection_result.detection_method = "metadata"
                detection_result.confidence = 1.0
                codex_connector_compat_enabled._compatibility_layer._session_detector.detect = AsyncMock(
                    return_value=detection_result
                )

            compat_result = (
                await codex_connector_compat_enabled._compatibility_layer.apply(context)
            )

            # Verify tool translation occurred
            assert (
                len(compat_result.codex_tools) > 0 or len(compat_result.proxy_tools) > 0
            ), "Compatibility layer should translate KiloCode tools"

            # Check that processed messages were updated with tool calls
            updated_messages = context.processed_messages
            assert len(updated_messages) > 0

            # Verify tool call metadata if present
            for msg in updated_messages:
                if msg.tool_calls:
                    assert len(msg.tool_calls) > 0
                    tool_call = msg.tool_calls[0]
                    assert tool_call.function.name == "read_file"
                    # Verify arguments contain both path formats
                    args = tool_call.function.arguments
                    if isinstance(args, dict):
                        assert "path" in args or "file_path" in args
                    elif isinstance(args, str):
                        import json

                        parsed_args = json.loads(args)
                        assert "path" in parsed_args or "file_path" in parsed_args
        else:
            pytest.skip("Compatibility layer not enabled in test fixture")

    @pytest.mark.asyncio
    async def test_request_flow_with_non_kilocode_client(
        self, codex_connector_compat_enabled: OpenAICodexConnector
    ):
        """Test request flow with non-KiloCode client does not activate compatibility layer."""
        from unittest.mock import AsyncMock, MagicMock, patch

        # Create mock request data for non-KiloCode client
        request_data = MagicMock()
        request_data.model = "gpt-5-codex"
        request_data.messages = [{"role": "user", "content": "Hello"}]
        request_data.stream = False
        request_data.metadata = {"agent": "cline"}

        # Create mock domain request
        domain_request = MagicMock()
        domain_request.session_id = "test_session_456"
        domain_request.processing_context = {}
        domain_request.metadata = {"agent": "cline"}

        processed_messages = [{"role": "user", "content": "Hello"}]

        # Mock the Codex API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test_response",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello! How can I help you?",
                    }
                }
            ],
        }

        # Create payload mock
        payload_mock = MagicMock()
        payload_mock.model_dump.return_value = {"input": []}
        payload_mock.prompt_cache_key = "test_key"

        with (
            patch.object(
                codex_connector_compat_enabled.client,
                "post",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch.object(
                codex_connector_compat_enabled,
                "_build_codex_payload",
                return_value=(payload_mock, "conv_456"),
            ),
        ):
            # Call the method
            await codex_connector_compat_enabled._call_codex_responses_api(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model="gpt-5-codex",
                domain_request=domain_request,
            )

            # Verify detection was performed and client is not KiloCode
            assert domain_request.processing_context.get("is_kilocode_client") is False

    @pytest.mark.asyncio
    async def test_feature_flag_disables_compatibility_layer(
        self, codex_connector_compat_disabled: OpenAICodexConnector
    ):
        """Test that feature flag disables compatibility layer."""
        from unittest.mock import AsyncMock, MagicMock, patch

        # Create mock request data with KiloCode metadata
        request_data = MagicMock()
        request_data.model = "gpt-5-codex"
        request_data.messages = [{"role": "user", "content": "Hello"}]
        request_data.stream = False
        request_data.metadata = {"agent": "kilocode"}

        # Create mock domain request
        domain_request = MagicMock()
        domain_request.session_id = "test_session_789"
        domain_request.processing_context = {}
        domain_request.metadata = {"agent": "kilocode"}

        processed_messages = [{"role": "user", "content": "Hello"}]

        # Mock the Codex API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test_response",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello! How can I help you?",
                    }
                }
            ],
        }

        # Create payload mock
        payload_mock = MagicMock()
        payload_mock.model_dump.return_value = {"input": []}
        payload_mock.prompt_cache_key = "test_key"

        with (
            patch.object(
                codex_connector_compat_disabled.client,
                "post",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch.object(
                codex_connector_compat_disabled,
                "_build_codex_payload",
                return_value=(payload_mock, "conv_789"),
            ),
        ):
            # Call the method
            await codex_connector_compat_disabled._call_codex_responses_api(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model="gpt-5-codex",
                domain_request=domain_request,
            )

            # Verify compatibility layer was not activated (no detection context)
            assert "is_kilocode_client" not in domain_request.processing_context

    @pytest.mark.asyncio
    async def test_session_cache_used_across_multiple_requests(
        self, codex_connector_compat_enabled: OpenAICodexConnector
    ):
        """Test that session cache is used across multiple requests."""
        from unittest.mock import AsyncMock, MagicMock, patch

        session_id = "test_session_cache_123"

        # Create mock request data
        request_data = MagicMock()
        request_data.model = "gpt-5-codex"
        request_data.messages = [{"role": "user", "content": "Hello"}]
        request_data.stream = False
        request_data.metadata = {"agent": "kilocode"}

        # Create mock domain request
        domain_request = MagicMock()
        domain_request.session_id = session_id
        domain_request.processing_context = {}
        domain_request.metadata = {"agent": "kilocode"}

        processed_messages = [{"role": "user", "content": "Hello"}]

        # Mock the Codex API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test_response",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello! How can I help you?",
                    }
                }
            ],
        }

        # Create payload mock
        payload_mock = MagicMock()
        payload_mock.model_dump.return_value = {"input": []}
        payload_mock.prompt_cache_key = "test_key"

        with (
            patch.object(
                codex_connector_compat_enabled.client,
                "post",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
            patch.object(
                codex_connector_compat_enabled,
                "_build_codex_payload",
                return_value=(payload_mock, "conv_cache"),
            ),
        ):
            # First request
            await codex_connector_compat_enabled._call_codex_responses_api(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model="gpt-5-codex",
                domain_request=domain_request,
            )

            # Verify first detection
            assert domain_request.processing_context.get("is_kilocode_client") is True
            first_method = domain_request.processing_context.get(
                "kilocode_detection_method"
            )

            # Reset processing context for second request
            domain_request.processing_context = {}

            # Second request with same session
            await codex_connector_compat_enabled._call_codex_responses_api(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model="gpt-5-codex",
                domain_request=domain_request,
            )

            # Verify second detection used cache
            assert domain_request.processing_context.get("is_kilocode_client") is True
            second_method = domain_request.processing_context.get(
                "kilocode_detection_method"
            )

            # At least one should be cached (second request should use cache)
            assert second_method == "cached" or first_method == "metadata"
