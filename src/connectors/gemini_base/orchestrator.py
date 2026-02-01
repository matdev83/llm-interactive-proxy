"""
Code Assist orchestration helpers for Gemini connectors.

This module keeps the linear streaming/non-streaming flows small by
wrapping the prepare -> execute -> accumulate/post-process steps.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any, cast

from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.policies import IRetryPolicy
from src.connectors.gemini_base.response_accumulator import (
    StreamingResponseAccumulator,
)
from src.connectors.gemini_base.streaming_executor import (
    ITokenRefresher,
    StreamingExecutor,
)
from src.connectors.gemini_base.thought_signature_service import ThoughtSignatureService
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)


StreamWrapper = Callable[
    [AsyncIterator[ProcessedResponse]], AsyncIterator[ProcessedResponse]
]
"""Type alias for optional stream transformation functions.

This type represents a pure function that transforms a stream of ProcessedResponse
chunks. It is used for optional VTC (tool call) features that intercept and process
tool calls in streaming responses.

**Data Flow**: This type flows:
- Produced by `IVtcWrapperBuilder.build()` when VTC is enabled
- Consumed by `ICodeAssistOrchestrator.run_streaming()` as optional `stream_wrapper` parameter
- Applied to transform `AsyncIterator[ProcessedResponse]` streams

**Service Boundaries**: Enables optional feature injection without coupling execution
to VTC implementation details. Returns None when VTC is disabled, allowing graceful degradation.

**Invariants**: Wrapper functions must be pure (no side effects) and preserve chunk ordering.
"""


class CodeAssistOrchestrator:
    """Owns streaming/non-streaming orchestration for the Gemini connector."""

    def __init__(
        self,
        *,
        streaming_executor: StreamingExecutor,
        response_post_processor: Any,
        thought_signature_service: ThoughtSignatureService,
        retry_policy: IRetryPolicy | None = None,
        backend_type: str = "gemini",
    ) -> None:
        self._streaming_executor = streaming_executor
        self._response_post_processor = response_post_processor
        self._thought_signature_service = thought_signature_service
        self._retry_policy = retry_policy
        self._backend_type = backend_type

    async def run_streaming(
        self,
        *,
        prepared: PreparedChatRequest,
        url: str,
        token_refresher: ITokenRefresher,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
        stream_wrapper: StreamWrapper | None = None,
    ) -> StreamingResponseEnvelope:
        """Execute a streaming request with optional wrapping.

        Note: Prefetching was removed to prevent blocking response headers and keepalives
        during long backend wait times (e.g. large prompts or cold starts).
        """
        base_generator = self._streaming_executor.execute(
            prepared=prepared,
            url=url,
            token_refresher=token_refresher,
            thought_signature_callback=thought_signature_callback,
            key_name=key_name,
            retry_policy=self._retry_policy,
        )

        generator: AsyncIterator[ProcessedResponse] = base_generator
        if stream_wrapper is not None:
            generator = stream_wrapper(generator)

        async def to_generator(
            iterator: AsyncIterator[ProcessedResponse],
        ) -> AsyncGenerator[ProcessedResponse, None]:
            async for item in iterator:
                yield item

        generator_as_gen = to_generator(generator)
        generator_as_gen = self._drop_plain_stop(generator_as_gen)

        envelope = StreamingResponseEnvelope(
            content=generator_as_gen,
            media_type="text/event-stream",
            headers={},
        )

        processed = await self._response_post_processor.process_streaming(
            envelope, prepared.effective_model
        )

        return cast(StreamingResponseEnvelope, processed)

    async def run_non_streaming(
        self,
        *,
        prepared: PreparedChatRequest,
        url: str,
        token_refresher: ITokenRefresher,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
    ) -> ResponseEnvelope:
        """Execute via streaming endpoint and accumulate for non-streaming clients."""
        stream_start = time.monotonic()
        streaming_envelope = await self.run_streaming(
            prepared=prepared,
            url=url,
            token_refresher=token_refresher,
            thought_signature_callback=thought_signature_callback,
            key_name=key_name,
        )
        stream_duration = time.monotonic() - stream_start

        accumulate_start = time.monotonic()
        accumulator = StreamingResponseAccumulator(backend_type=self._backend_type)
        response = await accumulator.accumulate(streaming_envelope)
        accumulate_duration = time.monotonic() - accumulate_start

        processed = cast(
            ResponseEnvelope,
            self._response_post_processor.process(response, prepared.effective_model),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Non-stream orchestration durations: stream=%.3fs accumulate=%.3fs (model=%s, session=%s)",
                stream_duration,
                accumulate_duration,
                prepared.effective_model,
                prepared.session_id,
            )

        return processed

    async def _drop_plain_stop(
        self, iterator: AsyncIterator[ProcessedResponse]
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """Filter out stop chunks without usage; executor will emit a final usage stop."""
        async for processed in iterator:
            content = getattr(processed, "content", None)
            metadata = (
                dict(processed.metadata)
                if hasattr(processed, "metadata") and processed.metadata
                else {}
            )

            if isinstance(content, dict):
                choices = content.get("choices", [])
                if choices and isinstance(choices[0], dict):
                    finish = choices[0].get("finish_reason") or (
                        choices[0].get("delta", {}) or {}
                    ).get("finish_reason")
                    if finish in ("stop", "stop_sequence") and "usage" not in content:
                        delta = choices[0].get("delta", {}) or {}
                        message = choices[0].get("message", {}) or {}
                        has_content = bool(
                            delta.get("content") or message.get("content")
                        )
                        has_tools = bool(
                            delta.get("tool_calls") or message.get("tool_calls")
                        )
                        has_reasoning = bool(
                            delta.get("reasoning_content")
                            or delta.get("reasoning")
                            or delta.get("thinking")
                            or delta.get("thought")
                            or message.get("reasoning_content")
                            or message.get("reasoning")
                            or message.get("thinking")
                            or message.get("thought")
                        )

                        has_accumulated = bool(
                            metadata.get("accumulated_content")
                            or metadata.get("accumulated_reasoning")
                        )
                        if not (
                            has_content or has_tools or has_reasoning or has_accumulated
                        ):
                            continue
            yield processed


__all__ = ["CodeAssistOrchestrator", "StreamWrapper"]
