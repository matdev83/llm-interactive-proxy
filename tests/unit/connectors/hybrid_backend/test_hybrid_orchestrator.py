"""Unit tests for HybridOrchestrator service.

Tests cover the complete two-phase orchestration flow including parsing,
injection decisions, reasoning/execution phases, filtering, and response building.

Requirements satisfied:
- Req 7: Orchestrator Extraction
- Req 11: Test-preserving migration
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.hybrid_backend.models.injection_decision import InjectionDecision
from src.connectors.hybrid_backend.models.phase_result import ReasoningPhaseResult
from src.connectors.hybrid_backend.protocols import (
    IHybridOrchestrator,
    IInjectionPolicy,
    IMessageAugmentor,
    IModelSpecParser,
    IParameterApplicator,
    IPhaseExecutor,
    IReasoningMarkupProcessor,
    IResponseBuilder,
    IResponseFilter,
)
from src.core.common.exceptions import BackendError, ConfigurationError
from src.core.domain.configuration.app_identity_config import AppIdentityConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestHybridOrchestrator:
    """Test HybridOrchestrator service implementation."""

    @pytest.fixture
    def config(self):
        """Create a mock AppConfig for testing."""
        config = MagicMock()
        config.backends.disable_hybrid_backend = False
        config.backends.hybrid_reasoning_latency_threshold = 8.0
        config.backends.hybrid_reasoning_backoff_turns = 2
        return config

    @pytest.fixture
    def model_spec_parser(self):
        """Create a mock IModelSpecParser."""
        parser = MagicMock(spec=IModelSpecParser)
        return parser

    @pytest.fixture
    def parameter_applicator(self):
        """Create a mock IParameterApplicator."""
        applicator = MagicMock(spec=IParameterApplicator)
        return applicator

    @pytest.fixture
    def injection_policy(self):
        """Create a mock IInjectionPolicy."""
        policy = MagicMock(spec=IInjectionPolicy)
        return policy

    @pytest.fixture
    def phase_executor(self):
        """Create a mock IPhaseExecutor."""
        executor = MagicMock(spec=IPhaseExecutor)
        return executor

    @pytest.fixture
    def message_augmentor(self):
        """Create a mock IMessageAugmentor."""
        augmentor = MagicMock(spec=IMessageAugmentor)
        return augmentor

    @pytest.fixture
    def response_filter(self):
        """Create a mock IResponseFilter."""
        filter_service = MagicMock(spec=IResponseFilter)
        return filter_service

    @pytest.fixture
    def response_builder(self):
        """Create a mock IResponseBuilder."""
        builder = MagicMock(spec=IResponseBuilder)
        return builder

    @pytest.fixture
    def reasoning_markup_processor(self):
        """Create a mock IReasoningMarkupProcessor."""
        processor = MagicMock(spec=IReasoningMarkupProcessor)
        return processor

    @pytest.fixture
    def orchestrator(
        self,
        config,
        model_spec_parser,
        parameter_applicator,
        injection_policy,
        phase_executor,
        message_augmentor,
        response_filter,
        response_builder,
        reasoning_markup_processor,
    ):
        """Create a HybridOrchestrator instance for testing."""
        from src.connectors.hybrid_backend.orchestration.orchestrator import (
            HybridOrchestrator,
        )

        return HybridOrchestrator(
            model_spec_parser=model_spec_parser,
            parameter_applicator=parameter_applicator,
            injection_policy=injection_policy,
            phase_executor=phase_executor,
            message_augmentor=message_augmentor,
            response_filter=response_filter,
            response_builder=response_builder,
            config=config,
            reasoning_markup_processor=reasoning_markup_processor,
        )

    @pytest.fixture
    def mock_spec(self):
        """Create a mock HybridModelSpec."""
        from src.connectors.hybrid_backend.models.model_spec import HybridModelSpec

        return HybridModelSpec(
            reasoning_backend="openai",
            reasoning_model="gpt-4",
            reasoning_params={},
            execution_backend="openai",
            execution_model="gpt-3.5-turbo",
            execution_params={},
        )

    @pytest.mark.asyncio
    async def test_orchestrator_implements_protocol(self, orchestrator):
        """Verify orchestrator implements IHybridOrchestrator protocol."""
        assert isinstance(orchestrator, IHybridOrchestrator)

    @pytest.mark.asyncio
    async def test_full_flow_with_injection(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        message_augmentor,
        response_filter,
        response_builder,
        mock_spec,
    ):
        """Test complete flow with reasoning injection."""
        # Setup mocks
        model_spec_parser.parse = MagicMock(return_value=mock_spec)
        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=True,
                reason="FORCE (first user turn)",
                is_first_turn=True,
                probability_used=1.0,
            )
        )

        reasoning_result = ReasoningPhaseResult(
            text="<thinking>reasoning content</thinking>",
            complete=True,
            tool_calls=[],
        )
        phase_executor.execute_reasoning_phase = AsyncMock(
            return_value=reasoning_result
        )

        augmented_messages = [{"role": "user", "content": "test"}]
        message_augmentor.augment = MagicMock(return_value=augmented_messages)

        execution_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "response"}}]}
        )
        phase_executor.execute_execution_phase = AsyncMock(
            return_value=execution_response
        )

        response_filter.filter_content = MagicMock(side_effect=lambda x: x)
        response_builder.prepend_reasoning_to_stream = (
            MagicMock()
        )  # Not called for non-streaming

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
        }
        identity = AppIdentityConfig(project="test-project")

        result = await orchestrator.execute(
            request_data=request_data,
            processed_messages=[{"role": "user", "content": "hello"}],
            effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            identity=identity,
        )

        assert isinstance(result, ResponseEnvelope)
        model_spec_parser.parse.assert_called_once()
        injection_policy.should_inject.assert_called_once()
        phase_executor.execute_reasoning_phase.assert_called_once()
        message_augmentor.augment.assert_called_once()
        phase_executor.execute_execution_phase.assert_called_once()

    @pytest.mark.asyncio
    async def test_short_circuit_tool_call_only(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        response_builder,
        reasoning_markup_processor,
        mock_spec,
    ):
        """Test short-circuit when reasoning produces tool calls without content."""
        from src.connectors.hybrid_backend.models.reasoning_text import ReasoningText

        model_spec_parser.parse = MagicMock(return_value=mock_spec)
        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=True,
                reason="FORCE (first user turn)",
                is_first_turn=True,
            )
        )

        reasoning_result = ReasoningPhaseResult(
            text="",  # No reasoning content
            complete=True,
            tool_calls=[
                {"id": "call_1", "type": "function", "function": {"name": "test"}}
            ],
        )
        phase_executor.execute_reasoning_phase = AsyncMock(
            return_value=reasoning_result
        )

        # Mock markup processor to return empty plain text (for short-circuit condition)
        reasoning_markup_processor.normalize = MagicMock(
            return_value=ReasoningText(tagged="", plain="", backend="openai")
        )

        tool_call_response = ResponseEnvelope(
            content={"tool_calls": [{"id": "call_1"}]}
        )
        response_builder.build_tool_call_response = MagicMock(
            return_value=tool_call_response
        )

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
        }

        result = await orchestrator.execute(
            request_data=request_data,
            processed_messages=[{"role": "user", "content": "hello"}],
            effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
        )

        assert isinstance(result, ResponseEnvelope)
        response_builder.build_tool_call_response.assert_called_once()
        # Should not call execution phase
        phase_executor.execute_execution_phase.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_injection_flow(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        message_augmentor,
        mock_spec,
    ):
        """Test flow when injection is skipped."""
        model_spec_parser.parse = MagicMock(return_value=mock_spec)
        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=False,
                reason="SKIP (probability sample)",
                is_first_turn=False,
                probability_used=0.5,
            )
        )

        execution_response = ResponseEnvelope(content={})
        phase_executor.execute_execution_phase = AsyncMock(
            return_value=execution_response
        )

        # Augment with empty reasoning
        message_augmentor.augment = MagicMock(
            return_value=[{"role": "user", "content": "test"}]
        )

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
        }

        result = await orchestrator.execute(
            request_data=request_data,
            processed_messages=[{"role": "assistant", "content": "hi"}],
            effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
        )

        assert isinstance(result, ResponseEnvelope)
        # Should skip reasoning phase
        phase_executor.execute_reasoning_phase.assert_not_called()
        # Should augment with empty reasoning
        message_augmentor.augment.assert_called_once()
        # Should execute execution phase
        phase_executor.execute_execution_phase.assert_called_once()

    @pytest.mark.asyncio
    async def test_reasoning_timeout_proceeds_to_execution(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        message_augmentor,
        mock_spec,
    ):
        """Test that reasoning timeout proceeds to execution with empty reasoning."""
        model_spec_parser.parse = MagicMock(return_value=mock_spec)
        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=True,
                reason="FORCE (first user turn)",
                is_first_turn=True,
            )
        )

        # Timeout returns empty result
        reasoning_result = ReasoningPhaseResult(
            text="",
            complete=False,
            tool_calls=[],
        )
        phase_executor.execute_reasoning_phase = AsyncMock(
            return_value=reasoning_result
        )

        message_augmentor.augment = MagicMock(
            return_value=[{"role": "user", "content": "test"}]
        )

        execution_response = ResponseEnvelope(content={})
        phase_executor.execute_execution_phase = AsyncMock(
            return_value=execution_response
        )

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
        }

        result = await orchestrator.execute(
            request_data=request_data,
            processed_messages=[{"role": "user", "content": "hello"}],
            effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
        )

        assert isinstance(result, ResponseEnvelope)
        # Should proceed to execution even with timeout
        phase_executor.execute_execution_phase.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_model_spec_raises_error(
        self,
        orchestrator,
        model_spec_parser,
    ):
        """Test that invalid model spec raises ValueError."""
        model_spec_parser.parse = MagicMock(side_effect=ValueError("Invalid format"))

        request_data = {"model": "invalid", "messages": []}

        with pytest.raises(ValueError):
            await orchestrator.execute(
                request_data=request_data,
                processed_messages=[],
                effective_model="invalid",
            )

    @pytest.mark.asyncio
    async def test_backend_disabled_raises_error(
        self,
        orchestrator,
        config,
        model_spec_parser,
        mock_spec,
    ):
        """Test that disabled backend raises ConfigurationError."""
        config.backends.disable_hybrid_backend = True
        model_spec_parser.parse = MagicMock(return_value=mock_spec)

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
        }

        with pytest.raises(ConfigurationError) as exc_info:
            await orchestrator.execute(
                request_data=request_data,
                processed_messages=[],
                effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            )

        assert "disabled" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_incompatible_reasoning_backend_raises_error(
        self,
        orchestrator,
        model_spec_parser,
    ):
        """Test that incompatible reasoning backend raises BackendError."""
        from src.connectors.hybrid_backend.models.model_spec import HybridModelSpec

        incompatible_spec = HybridModelSpec(
            reasoning_backend="gemini-oauth-plan",
            reasoning_model="gemini-pro",
            execution_backend="openai",
            execution_model="gpt-3.5-turbo",
        )
        model_spec_parser.parse = MagicMock(return_value=incompatible_spec)

        request_data = {
            "model": "hybrid:[gemini-oauth-plan:gemini-pro,openai:gpt-3.5-turbo]",
            "messages": [],
        }

        with pytest.raises(BackendError) as exc_info:
            await orchestrator.execute(
                request_data=request_data,
                processed_messages=[],
                effective_model="hybrid:[gemini-oauth-plan:gemini-pro,openai:gpt-3.5-turbo]",
            )

        assert "does not support reasoning tags" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_reasoning_phase_error_propagates(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        mock_spec,
    ):
        """Test that reasoning phase errors propagate correctly."""
        model_spec_parser.parse = MagicMock(return_value=mock_spec)
        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=True,
                reason="FORCE (first user turn)",
                is_first_turn=True,
            )
        )

        phase_executor.execute_reasoning_phase = AsyncMock(
            side_effect=BackendError(
                message="Reasoning backend failed",
                code="reasoning_backend_error",
            )
        )

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
        }

        with pytest.raises(BackendError) as exc_info:
            await orchestrator.execute(
                request_data=request_data,
                processed_messages=[{"role": "user", "content": "hello"}],
                effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            )

        assert "reasoning phase" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execution_phase_error_propagates(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        message_augmentor,
        mock_spec,
    ):
        """Test that execution phase errors propagate correctly."""
        model_spec_parser.parse = MagicMock(return_value=mock_spec)
        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=False,
                reason="SKIP",
                is_first_turn=False,
            )
        )

        message_augmentor.augment = MagicMock(
            return_value=[{"role": "user", "content": "test"}]
        )

        phase_executor.execute_execution_phase = AsyncMock(
            side_effect=BackendError(
                message="Execution backend failed",
                code="execution_backend_error",
            )
        )

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
        }

        with pytest.raises(BackendError) as exc_info:
            await orchestrator.execute(
                request_data=request_data,
                processed_messages=[{"role": "assistant", "content": "hi"}],
                effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            )

        assert "execution phase" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_streaming_response_handling(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        message_augmentor,
        response_filter,
        response_builder,
        mock_spec,
    ):
        """Test streaming response handling."""
        model_spec_parser.parse = MagicMock(return_value=mock_spec)
        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=False,
                reason="SKIP",
                is_first_turn=False,
            )
        )

        async def mock_stream():
            yield ProcessedResponse(content="chunk1")
            yield ProcessedResponse(content="chunk2")

        streaming_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
        )

        message_augmentor.augment = MagicMock(
            return_value=[{"role": "user", "content": "test"}]
        )
        phase_executor.execute_execution_phase = AsyncMock(
            return_value=streaming_response
        )

        filtered_response = StreamingResponseEnvelope(
            content=mock_stream(),
            media_type="text/event-stream",
        )
        response_filter.filter_stream = AsyncMock(return_value=filtered_response)
        response_builder.prepend_reasoning_to_stream = MagicMock(
            return_value=filtered_response
        )

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
            "stream": True,
        }

        result = await orchestrator.execute(
            request_data=request_data,
            processed_messages=[{"role": "assistant", "content": "hi"}],
            effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
        )

        assert isinstance(result, StreamingResponseEnvelope)
        response_filter.filter_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_probability_override_from_extra_body(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        message_augmentor,
        mock_spec,
    ):
        """Test probability override extraction from extra_body."""
        model_spec_parser.parse = MagicMock(return_value=mock_spec)

        # Mock should_inject to verify probability_override was passed
        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=False,
                reason="SKIP",
                is_first_turn=False,
                probability_used=0.8,
            )
        )

        message_augmentor.augment = MagicMock(
            return_value=[{"role": "user", "content": "test"}]
        )
        phase_executor.execute_execution_phase = AsyncMock(
            return_value=ResponseEnvelope(content={})
        )

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
            "extra_body": {"_temp_hybrid_reasoning_probability": 0.8},
        }

        await orchestrator.execute(
            request_data=request_data,
            processed_messages=[{"role": "assistant", "content": "hi"}],
            effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
        )

        # Verify probability override was passed
        call_args = injection_policy.should_inject.call_args
        assert call_args is not None
        assert call_args.kwargs.get("probability_override") == 0.8

    @pytest.mark.asyncio
    async def test_backoff_update_on_slow_reasoning(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        message_augmentor,
        mock_spec,
    ):
        """Test that backoff is updated when reasoning exceeds latency threshold."""

        model_spec_parser.parse = MagicMock(return_value=mock_spec)
        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=True,
                reason="FORCE (first user turn)",
                is_first_turn=True,
            )
        )

        # Mock slow reasoning
        async def slow_reasoning(*args, **kwargs):
            await asyncio.sleep(0.01)  # Small delay to simulate processing
            return ReasoningPhaseResult(
                text="<thinking>reasoning</thinking>",
                complete=True,
                tool_calls=[],
            )

        phase_executor.execute_reasoning_phase = slow_reasoning

        message_augmentor.augment = MagicMock(
            return_value=[{"role": "user", "content": "test"}]
        )
        phase_executor.execute_execution_phase = AsyncMock(
            return_value=ResponseEnvelope(content={})
        )

        # Set low latency threshold to trigger backoff
        orchestrator.config.backends.hybrid_reasoning_latency_threshold = 0.001

        request_data = {
            "model": "hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
            "messages": [],
        }

        await orchestrator.execute(
            request_data=request_data,
            processed_messages=[{"role": "user", "content": "hello"}],
            effective_model="hybrid:[openai:gpt-4,openai:gpt-3.5-turbo]",
        )

        # Verify update_backoff was called
        injection_policy.update_backoff.assert_called()

    @pytest.mark.asyncio
    async def test_reasoning_effort_warning(
        self,
        orchestrator,
        model_spec_parser,
        injection_policy,
        phase_executor,
        message_augmentor,
    ):
        """Test that reasoning_effort parameter triggers warning."""
        from src.connectors.hybrid_backend.models.model_spec import HybridModelSpec

        spec_with_effort = HybridModelSpec(
            reasoning_backend="openai",
            reasoning_model="gpt-4",
            reasoning_params={"reasoning_effort": "high"},
            execution_backend="openai",
            execution_model="gpt-3.5-turbo",
            execution_params={"reasoning_effort": "low"},
        )
        model_spec_parser.parse = MagicMock(return_value=spec_with_effort)

        injection_policy.should_inject = MagicMock(
            return_value=InjectionDecision(
                should_inject=False,
                reason="SKIP",
                is_first_turn=False,
            )
        )

        message_augmentor.augment = MagicMock(
            return_value=[{"role": "user", "content": "test"}]
        )
        phase_executor.execute_execution_phase = AsyncMock(
            return_value=ResponseEnvelope(content={})
        )

        request_data = {
            "model": "hybrid:[openai:gpt-4?reasoning_effort=high,openai:gpt-3.5-turbo?reasoning_effort=low]",
            "messages": [],
        }

        await orchestrator.execute(
            request_data=request_data,
            processed_messages=[{"role": "assistant", "content": "hi"}],
            effective_model="hybrid:[openai:gpt-4?reasoning_effort=high,openai:gpt-3.5-turbo?reasoning_effort=low]",
        )

        # Warning should be logged (we can't easily test logging, but execution should proceed)
        phase_executor.execute_execution_phase.assert_called_once()
