"""
Integration helpers for connecting backends to the streaming pipeline.

This module provides helper functions that backends can use to integrate
with the new streaming pipeline orchestrator.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast

from src.core.common.exceptions import LLMProxyError, RateLimitExceededError
from src.core.domain.chat import ChatRequest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import IStreamProcessor, handle_streaming_error
from src.core.ports.streaming_orchestrator import (
    create_pipeline_for_provider,
    safe_aclose,
)
from src.core.ports.streaming_processors import (
    LoopDetectionProcessor as PortsLoopDetectionProcessor,
)
from src.core.ports.streaming_processors import (
    ThinkTagsProcessor,
    ToolCallDeltaStabilizerProcessor,
)
from src.core.ports.streaming_processors import (
    ToolCallRepairProcessor as PortsToolCallRepairProcessor,
)
from src.core.services.streaming.chunk_normalizer import (
    normalize_to_processed_chunk_content,
)
from src.core.services.streaming.error_mapping import StreamingErrorMapper
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor as ServiceToolCallRepairProcessor,
)
from src.core.services.streaming.vtc_postprocessor import VTCPostProcessor
from src.core.services.streaming.vtc_preprocessor import VTCPreProcessor
from src.core.services.tool_call_repair_service import ToolCallRepairService

logger = logging.getLogger(__name__)

# String / type tokens that indicate a rate-limited first SSE frame when HTTP status
# was already 200 (some OpenAI-compatible gateways stream errors as SSE only).
_RATE_LIMIT_ERROR_CODE_TOKENS: frozenset[str] = frozenset(
    {
        "rate_limit_exceeded",
        "too_many_requests",
        "requests_per_minute_exceeded",
        "rpm_limit_exceeded",
        "tpm_limit_exceeded",
        "tenant_rate_limited",
        "usage_limit_reached",
    }
)


def _error_payload_implies_rate_limit(payload: dict[str, Any]) -> bool:
    """Return True when a JSON object (often ``error``) describes a rate limit."""
    err_type = payload.get("type")
    if isinstance(err_type, str) and err_type.strip():
        lowered = err_type.strip().lower()
        if lowered in _RATE_LIMIT_ERROR_CODE_TOKENS:
            return True
        if "rate" in lowered and "limit" in lowered:
            return True

    code = payload.get("code")
    if isinstance(code, int) and code == 429:
        return True
    if isinstance(code, float) and code.is_integer() and int(code) == 429:
        return True
    if isinstance(code, str) and code.strip():
        lowered = code.strip().lower()
        if lowered in _RATE_LIMIT_ERROR_CODE_TOKENS or lowered == "429":
            return True

    sc = payload.get("status_code")
    if isinstance(sc, int) and sc == 429:
        return True
    if isinstance(sc, float) and sc.is_integer() and int(sc) == 429:
        return True
    if isinstance(sc, str):
        stripped = sc.strip()
        if stripped.isdigit() and int(stripped) == 429:
            return True

    return False


def _try_extract_http_status_from_first_sse_chunk(first_chunk: bytes) -> int | None:
    """Best-effort: extract HTTP-like status from an SSE error chunk.

    We want to surface early backend errors as a non-200 HTTP status on the streaming
    response when possible. Many clients (including OpenAI-compatible SDKs) treat
    non-200 as a hard failure and will stop retry loops.

    Expected formats:
    - data: {"choices": [...], "error": {"status_code": 404, ...}}
    - data: {"choices": [{"finish_reason": "error"}], ...}
    - data: {"error": {"code": "rate_limit_exceeded", ...}}  (no numeric status)
    """
    try:
        text = first_chunk.decode("utf-8", errors="ignore")
    except Exception:
        return None

    # Consider only the first SSE data line.
    # (Some serializers emit multiple frames; we only need a hint.)
    for block in text.replace("\r\n", "\n").split("\n\n"):
        stripped = block.strip()
        if not stripped.startswith("data:"):
            continue
        data_part = stripped[5:].strip()
        if not data_part or data_part == "[DONE]":
            continue
        try:
            obj = json.loads(data_part)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        # Prefer explicit error.status_code
        err = obj.get("error")
        if isinstance(err, dict):
            sc = err.get("status_code")
            if isinstance(sc, int):
                return sc
            if isinstance(sc, float) and sc.is_integer():
                return int(sc)
            # Some providers encode code as integer.
            code = err.get("code")
            if isinstance(code, int):
                return code
            if isinstance(code, float) and code.is_integer():
                return int(code)
            if _error_payload_implies_rate_limit(err):
                return 429
        elif isinstance(err, str) and "rate" in err.lower() and "limit" in err.lower():
            return 429

        if _error_payload_implies_rate_limit(obj):
            return 429

        # Fallback: if it looks like an OpenAI error chunk, treat as 500.
        choices = obj.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict) and first.get("finish_reason") == "error":
                return 500
        return None
    return None


def _resolve_ports_streaming_loop_detection_enabled(
    *,
    explicit: bool | None,
    domain_request: ChatRequest | None,
) -> bool:
    """Whether to attach the ports :class:`LoopDetectionProcessor` to the pipeline.

    Precedence: ``explicit`` (tests / call-site override), per-request field on
    ``domain_request``, then :attr:`AppConfig.session.streaming_loop_detection_enabled`.
    """
    if explicit is not None:
        return explicit
    if domain_request is not None:
        per_request = domain_request.streaming_loop_detection_enabled
        if per_request is not None:
            return bool(per_request)
    try:
        from src.core.config.app_config import AppConfig
        from src.core.di.services import get_or_build_service_provider

        provider = get_or_build_service_provider()
        app_config = provider.get_service(AppConfig)
        if app_config is None:
            return False
        return bool(
            getattr(app_config.session, "streaming_loop_detection_enabled", False)
        )
    except Exception:
        return False


async def integrate_streaming_pipeline(
    raw_stream: AsyncIterator[object],
    provider: str,
    stream_id: str | None = None,
    enable_loop_detection: bool | None = None,
    enable_tool_call_repair: bool = True,
    enable_think_tags: bool = True,
    prompt_tokens: int | None = None,
    model_name: str | None = None,
    vtc_enabled: bool = False,
    yield_interval: int = 100,
    headers: dict[str, str] | None = None,
    domain_request: ChatRequest | None = None,
) -> StreamingResponseEnvelope:
    """Integrate a raw backend stream with the streaming pipeline.

    This function:
    1. Creates a pipeline with the appropriate normalizer for the provider
    2. Adds configured processors (loop detection, tool call repair, etc.)
    3. Processes the stream through the complete pipeline
    4. Returns a StreamingResponseEnvelope with ProcessedResponse chunks

    This provides backward compatibility while using the new infrastructure.

    Args:
        raw_stream: Raw async iterator from backend's stream_completion() (opaque provider-specific data)
        provider: Provider name ("openai", "anthropic", "gemini")
        stream_id: Optional stream identifier
        enable_loop_detection: When not ``None``, forces the loop detection processor
            on or off. When ``None`` (default), uses ``domain_request`` override if set,
            otherwise ``AppConfig.session.streaming_loop_detection_enabled``.
        domain_request: Optional domain request for per-request loop detection override
            (``streaming_loop_detection_enabled`` on the request model).
        enable_tool_call_repair: Whether to enable tool call repair processor
        enable_think_tags: Whether to enable think tags processor
        prompt_tokens: Optional prompt token count for usage calculation
        model_name: Optional model name for usage calculation
        vtc_enabled: Whether Virtual Tool Calling is enabled for this session
        yield_interval: Number of chunks to batch before yielding to event loop
        headers: Optional response headers from backend

    Returns:
        StreamingResponseEnvelope with processed chunks
    """
    enable_loop_detection_effective = _resolve_ports_streaming_loop_detection_enabled(
        explicit=enable_loop_detection,
        domain_request=domain_request,
    )

    processors: list[IStreamProcessor] = []

    # Lazy DI provider resolution - only fetch when needed.
    # This avoids triggering DI build hooks on simple streaming calls that don't need DI.
    _di_provider: IServiceProvider | None = None

    def _get_di_provider() -> IServiceProvider:
        nonlocal _di_provider
        if _di_provider is None:
            from src.core.di.services import get_or_build_service_provider

            _di_provider = get_or_build_service_provider()
        return _di_provider

    # VTC Pre-processor: FIRST in pipeline (converts XML to internal format)
    # This processor requires DI dependencies (StreamingContextRegistry)
    if vtc_enabled:
        di_provider = _get_di_provider()
        registry = di_provider.get_required_service(StreamingContextRegistry)
        processors.append(VTCPreProcessor(registry=registry))
        logger.debug("VTC pre-processor enabled for stream %s", stream_id)

    # Loop detection processor - stateless, can be created directly
    if enable_loop_detection_effective:
        processors.append(PortsLoopDetectionProcessor())

    # Service-based tool call repair processor - requires DI dependencies
    if enable_tool_call_repair:
        di_provider = _get_di_provider()
        repair_service = di_provider.get_service(ToolCallRepairService)
        if repair_service is not None:
            registry = di_provider.get_required_service(StreamingContextRegistry)
            processors.append(
                ServiceToolCallRepairProcessor(
                    tool_call_repair_service=repair_service,
                    registry=registry,
                )
            )
        else:
            logger.warning(
                "ToolCallRepairService not available in DI container; "
                "skipping service-based tool call repair processor. "
                "Ports-based processor will still be used.",
                extra={"stream_id": stream_id, "provider": provider},
            )

    # Ports-based tool call repair processor - stateless, can be created directly
    if enable_tool_call_repair:
        processors.append(PortsToolCallRepairProcessor())

    # Stabilize tool_call deltas (fill missing id/name on continuation chunks)
    if enable_tool_call_repair:
        processors.append(ToolCallDeltaStabilizerProcessor())

    # Think tags processor - stateless, can be created directly
    if enable_think_tags:
        processors.append(ThinkTagsProcessor())

    # Add usage calculation processor if prompt tokens are provided
    # This ensures usage is calculated after all other processors (like loop detection)
    # have potentially modified the content.
    if prompt_tokens is not None and model_name:
        from src.core.ports.usage_processor import UsageCalculationProcessor

        def _usage_processor_factory() -> IStreamProcessor:
            return cast(
                IStreamProcessor,
                UsageCalculationProcessor(
                    prompt_tokens=prompt_tokens, model_name=model_name
                ),
            )

        processors.append(_usage_processor_factory())

    # VTC Post-processor: LAST in pipeline (converts internal format back to XML)
    # This processor requires DI dependencies (StreamingContextRegistry)
    if vtc_enabled:
        di_provider = _get_di_provider()
        registry = di_provider.get_required_service(StreamingContextRegistry)
        processors.append(VTCPostProcessor(registry=registry))
        logger.debug("VTC post-processor enabled for stream %s", stream_id)

    # Create pipeline for the provider - normalizer must be constructed explicitly
    from src.core.ports.anthropic_normalizer import AnthropicStreamNormalizer
    from src.core.ports.gemini_normalizer import GeminiStreamNormalizer
    from src.core.ports.kiro_normalizer import KiroStreamNormalizer
    from src.core.ports.openai_normalizer import OpenAIStreamNormalizer

    # Select and construct normalizer based on provider (stateless adapter - no DI required)
    normalizer_map = {
        "openai": OpenAIStreamNormalizer,
        "anthropic": AnthropicStreamNormalizer,
        "gemini": GeminiStreamNormalizer,
        "kiro": KiroStreamNormalizer,
    }

    normalizer_class = normalizer_map.get(provider.lower())
    if not normalizer_class:
        logger.error(
            "Failed to create streaming pipeline for provider %s: Unsupported provider. "
            "No legacy fallback available.",
            provider,
        )
        error_chunk = await handle_streaming_error(
            ValueError(f"Unsupported provider: {provider}"), stream_id, provider
        )

        async def error_stream() -> AsyncIterator[ProcessedResponse]:
            normalized_content = normalize_to_processed_chunk_content(
                error_chunk.to_bytes()
            )
            yield ProcessedResponse(content=normalized_content)

        return StreamingResponseEnvelope(
            content=error_stream(),
            media_type="text/event-stream",
            headers=headers or {},
        )

    # Construct normalizer explicitly at call site (requirement 5.2)
    normalizer = normalizer_class()

    # Create pipeline for the provider
    try:
        pipeline = create_pipeline_for_provider(
            provider,
            processors=processors,
            normalizer=normalizer,
            yield_interval=yield_interval,
        )
    except ValueError as e:
        logger.error(
            "Failed to create streaming pipeline for provider %s: %s. No legacy fallback available.",
            provider,
            e,
            exc_info=True,
        )

        error_chunk = await handle_streaming_error(e, stream_id, provider)

        async def error_stream() -> AsyncIterator[ProcessedResponse]:
            normalized_content = normalize_to_processed_chunk_content(
                error_chunk.to_bytes()
            )
            yield ProcessedResponse(content=normalized_content)

        return StreamingResponseEnvelope(
            content=error_stream(),
            media_type="text/event-stream",
            headers=headers or {},
        )

    # Build the pipeline output iterator and prefetch the first chunk.
    # This allows us to:
    # - delay sending response headers until we have something to send
    # - surface early backend errors as non-200 HTTP status codes when possible
    output_iter = pipeline.process_stream(
        raw_stream,
        provider=provider,
        stream_id=stream_id,
        output_format="sse",
    )

    first_bytes: bytes | None = None
    status_code: int | None = None
    try:
        first_bytes = await anext(output_iter)
        status_code = _try_extract_http_status_from_first_sse_chunk(first_bytes)
    except StopAsyncIteration:
        # An empty stream is treated as an error; emit a terminal error chunk.
        err = ValueError("Upstream stream ended without any chunks")
        error_chunk = await handle_streaming_error(err, stream_id, provider)
        first_bytes = error_chunk.to_bytes()
        # Use an explicit error status so transport adapters do not treat this as
        # a successful no-content response and silently suppress the body.
        status_code = 502
    except Exception as e:
        mapped_error = StreamingErrorMapper.map_backend_error(e, provider, stream_id)
        # Early rate-limit failures should bubble up as retryable domain errors.
        # This preserves provider retry metadata (e.g., Retry-After) for callers.
        if isinstance(mapped_error, RateLimitExceededError):
            raise mapped_error
        error_chunk = await handle_streaming_error(mapped_error, stream_id, provider)

        async def error_stream() -> AsyncIterator[ProcessedResponse]:
            yielded_content = error_chunk.to_bytes()
            yield ProcessedResponse(
                content=normalize_to_processed_chunk_content(yielded_content)
            )

        return StreamingResponseEnvelope(
            content=error_stream(),
            media_type="text/event-stream",
            headers=headers or {},
            status_code=(
                mapped_error.status_code
                if hasattr(mapped_error, "status_code") and mapped_error.status_code
                else 500
            ),
        )

    async def processed_stream() -> AsyncIterator[ProcessedResponse]:
        """Wrap pipeline output in ProcessedResponse for backward compatibility."""
        emitted_any = False
        try:
            if first_bytes is not None:
                emitted_any = True
                yield ProcessedResponse(
                    content=normalize_to_processed_chunk_content(first_bytes)
                )
            async for sse_bytes in output_iter:
                emitted_any = True
                yield ProcessedResponse(
                    content=normalize_to_processed_chunk_content(sse_bytes)
                )
        except LLMProxyError as e:
            # If the stream already started, we can't change the HTTP status.
            # Emit a structured terminal error chunk so clients can stop waiting.
            # Domain errors are logged at WARNING level without stack trace.
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Domain error in streaming pipeline mid-stream",
                    extra={
                        "provider": provider,
                        "stream_id": stream_id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "emitted_any": emitted_any,
                    },
                )
            error_chunk = await handle_streaming_error(e, stream_id, provider)
            yield ProcessedResponse(
                content=normalize_to_processed_chunk_content(error_chunk.to_bytes())
            )
            return
        except Exception as e:
            # If the stream already started, we can't change the HTTP status.
            # Emit a structured terminal error chunk so clients can stop waiting.
            # Unexpected exceptions are logged at ERROR level with stack trace.
            logger.error(
                "Error in streaming pipeline",
                exc_info=True,
                extra={
                    "provider": provider,
                    "stream_id": stream_id,
                    "error": str(e),
                    "emitted_any": emitted_any,
                },
            )
            error_chunk = await handle_streaming_error(e, stream_id, provider)
            yield ProcessedResponse(
                content=normalize_to_processed_chunk_content(error_chunk.to_bytes())
            )
            return

    async def cancel_callback() -> None:
        """Cancel the raw stream if possible."""
        await safe_aclose(raw_stream, provider, stream_id)

    return StreamingResponseEnvelope(
        content=processed_stream(),
        media_type="text/event-stream",
        headers=headers or {},
        cancel_callback=cancel_callback,
        status_code=status_code if isinstance(status_code, int) else 200,
    )
