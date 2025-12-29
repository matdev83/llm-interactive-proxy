"""JSON response builder for response adapters."""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.usage_payload import UsagePayload
from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
    ReasoningInjector,
)
from src.core.transport.fastapi.adapters.protocols import (
    IHeaderSanitizer,
    IJSONSanitizer,
    IReasoningInjector,
    IUsageHeaderInjector,
)
from src.core.transport.fastapi.adapters.sanitization.header_sanitizer import (
    HeaderSanitizer,
)
from src.core.transport.fastapi.adapters.sanitization.json_sanitizer import (
    JSONSanitizer,
)
from src.core.transport.fastapi.adapters.usage.header_injector import (
    UsageHeaderInjector,
)
from src.core.utils.usage_recalculation import (
    extract_content_text,
    should_recalculate_usage,
)

if TYPE_CHECKING:
    from src.core.interfaces.usage_normalization_service_interface import (
        IUsageNormalizationService,
    )

logger = logging.getLogger(__name__)

try:
    from src.core.utils.token_count import count_tokens
except (ImportError, ModuleNotFoundError):
    if logger.isEnabledFor(logging.WARNING):
        logger.warning(
            "Could not import count_tokens from src.core.utils.token_count, using fallback that returns 0",
            exc_info=True,
        )

    def count_tokens_fallback(*args: Any, **kwargs: Any) -> int:
        return 0

    count_tokens = count_tokens_fallback


if TYPE_CHECKING:
    from src.core.interfaces.usage_normalization_service_interface import (
        IUsageNormalizationService,
    )

logger = logging.getLogger(__name__)


class JSONResponseBuilder:
    """Build FastAPI JSONResponse from ResponseEnvelope.

    Applies reasoning injection, usage normalization, content sanitization,
    and header filtering before creating the response.
    """

    def __init__(
        self,
        json_sanitizer: IJSONSanitizer | None = None,
        header_sanitizer: IHeaderSanitizer | None = None,
        usage_header_injector: IUsageHeaderInjector | None = None,
        reasoning_injector: IReasoningInjector | None = None,
        usage_normalization_service: IUsageNormalizationService | None = None,
    ) -> None:
        """Initialize JSON response builder.

        Args:
            json_sanitizer: Optional JSON sanitizer. Creates default if not provided.
            header_sanitizer: Optional header sanitizer. Creates default if not provided.
            usage_header_injector: Optional usage header injector. Creates default if not provided.
            reasoning_injector: Optional reasoning injector. Creates default if not provided.
            usage_normalization_service: Optional usage normalization service. Resolved from DI if not provided.
        """
        self._json_sanitizer = json_sanitizer or JSONSanitizer()
        self._header_sanitizer = header_sanitizer or HeaderSanitizer()
        self._usage_header_injector = usage_header_injector or UsageHeaderInjector()
        self._reasoning_injector = reasoning_injector or ReasoningInjector()
        self._usage_normalization_service = usage_normalization_service
        self._cached_usage_normalization_service: IUsageNormalizationService | None = (
            None
        )
        self._cached_usage_calculation_service: Any = None
        self._cached_steering_leak_protector: Any = None

    def _get_usage_normalization_service(self) -> IUsageNormalizationService | None:
        """Get usage normalization service from DI or instance.

        Returns:
            Usage normalization service or None if not available
        """
        if self._usage_normalization_service is not None:
            return self._usage_normalization_service

        if self._cached_usage_normalization_service is not None:
            return self._cached_usage_normalization_service

        # Try to resolve from DI
        try:
            from typing import cast

            from src.core.di.services import get_service_provider
            from src.core.interfaces.usage_normalization_service_interface import (
                IUsageNormalizationService,
            )

            provider = get_service_provider()
            if provider:
                self._cached_usage_normalization_service = provider.get_service(
                    cast(type, IUsageNormalizationService)
                )
                return self._cached_usage_normalization_service
        except ImportError:
            # Import failures - log at DEBUG since this is a lazy initialization helper
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Could not import dependencies for usage normalization service resolution",
                    exc_info=True,
                )
        except (RuntimeError, AttributeError, KeyError) as exc:
            # Service provider access errors - log at DEBUG since this is a lazy initialization helper
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Could not resolve usage normalization service from DI: %s",
                    type(exc).__name__,
                    exc_info=True,
                )
        except Exception as exc:
            # Catch-all for other unexpected exceptions
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Unexpected error resolving usage normalization service from DI: %s",
                    type(exc).__name__,
                    exc_info=True,
                )
        return None

    def build(
        self,
        envelope: ResponseEnvelope,
        *,
        context: RequestContext | None = None,
    ) -> JSONResponse:
        """Build JSONResponse from envelope.

        Args:
            envelope: Response envelope
            context: Optional request context for usage calculation

        Returns:
            FastAPI JSONResponse
        """
        # Normalize content
        prepared_content = self._prepare_json_content(envelope.content)

        # Apply reasoning injection
        prepared_content = self._reasoning_injector.inject_reasoning(
            prepared_content, getattr(envelope, "metadata", None) or {}, streaming=False
        )

        # Apply metadata (reasoning, steering_retry_occurred)
        if envelope.metadata and isinstance(prepared_content, dict):
            reasoning_meta = envelope.metadata.get(
                "reasoning"
            ) or envelope.metadata.get("reasoning_content")
            if reasoning_meta:
                metadata_section = prepared_content.setdefault("metadata", {})
                if isinstance(metadata_section, dict):
                    metadata_section.setdefault("reasoning", reasoning_meta)
                    metadata_section.setdefault("reasoning_content", reasoning_meta)

            if envelope.metadata.get("steering_retry_occurred"):
                metadata_section = prepared_content.setdefault("metadata", {})
                if isinstance(metadata_section, dict):
                    metadata_section["steering_retry_occurred"] = True

        # Ensure usage and apply to payload
        prepared_content, usage_data = self._ensure_usage(
            envelope, prepared_content, context
        )

        # Get headers and inject usage headers (Requirement 5.5)
        headers = envelope.headers or {}
        headers = self._usage_header_injector.inject_headers(
            headers, usage_data or {}, canonical_usage=envelope.canonical_usage
        )

        # Sanitize content and headers
        safe_content = self._json_sanitizer.sanitize(prepared_content)
        safe_headers = self._header_sanitizer.sanitize(headers)

        # Log if content-encoding survived sanitization (shouldn't happen)
        if "content-encoding" in {k.lower(): v for k, v in safe_headers.items()}:
            logger.debug("Content-Encoding survived sanitation: %s", safe_headers)

        # Sanitize and handle status code
        safe_status_code = self._sanitize_status_code(envelope.status_code)
        final_status_code = self._handle_backend_error_status_code(
            safe_content, safe_status_code
        )

        # Create JSON response
        return self._create_json_response(safe_content, final_status_code, safe_headers)

    def _prepare_json_content(self, content: Any) -> Any:
        """Prepare content for JSON serialization.

        Args:
            content: Content to prepare

        Returns:
            Prepared content (dict, list, or primitive)
        """
        if hasattr(content, "model_dump"):
            return content.model_dump()
        elif is_dataclass(content) and not isinstance(content, type):
            return asdict(content)
        return content

    def _ensure_usage(
        self,
        envelope: ResponseEnvelope,
        payload: Any,
        context: RequestContext | None = None,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Ensure usage information is present and aligned with transformed content.

        This function integrates with canonical usage normalization and UsageCalculationService:
        1. Use canonical usage when available (projected to protocol format)
        2. Use backend-provided usage when available
        3. Recalculate when proxy modifications occurred
        4. Preserve extended usage fields (reasoning_tokens, cached_tokens, cost)

        Args:
            envelope: The response envelope
            payload: The response payload
            context: Request context with modification tracking

        Returns:
            Tuple of (updated payload, usage dict in OpenRouter format)
        """
        # Lazy load and cache usage calculation service
        if self._cached_usage_calculation_service is None:
            from src.core.services.usage_calculation_service import (
                get_usage_calculation_service,
            )

            self._cached_usage_calculation_service = get_usage_calculation_service()
        service = self._cached_usage_calculation_service

        # Priority 1: Use canonical usage if available (Requirement 5.2)
        normalization_service = self._get_usage_normalization_service()
        if envelope.canonical_usage is not None and normalization_service is not None:
            # Extract existing usage from payload as UsagePayload for merging
            existing_payload: UsagePayload | None = None
            if isinstance(payload, dict):
                existing_usage_dict = payload.get("usage")
                if isinstance(existing_usage_dict, dict):
                    existing_payload = UsagePayload(payload=existing_usage_dict)

            # Project canonical usage to protocol format
            projected_payload = normalization_service.project_protocol_usage(
                canonical=envelope.canonical_usage, existing=existing_payload
            )

            if projected_payload is not None:
                usage_dict = projected_payload.payload
                # Apply usage to envelope and payload
                if isinstance(payload, dict):
                    payload["usage"] = usage_dict
                from src.core.domain.usage_summary import UsageSummary

                envelope.usage = UsageSummary.from_dict(usage_dict)
                return payload, usage_dict

        # Fallback to existing logic when canonical usage is not available
        # Get existing usage from envelope or payload
        existing_usage = self._normalize_usage_dict(envelope.usage)
        if existing_usage is None and isinstance(payload, dict):
            existing_usage = self._normalize_usage_dict(payload.get("usage"))

        model_name = self._resolve_model_name(envelope, payload)

        # Check if modifications require recalculation
        requires_recalc = False
        if context is not None:
            requires_recalc = context.requires_usage_recalculation()

        # Check metadata for recalculation flag
        metadata = getattr(envelope, "metadata", None)
        if isinstance(metadata, dict) and metadata.get("allow_usage_recalculation"):
            requires_recalc = True

        if requires_recalc or existing_usage is None:
            # Get prompt tokens hint from metadata
            prompt_tokens_hint = self._resolve_prompt_tokens(existing_usage, envelope)

            # Recalculate usage accounting for modifications
            usage_obj = service.ensure_usage(
                backend_usage=existing_usage,
                context=context,
                response_content=payload,
                model=model_name,
                force_recalculation=requires_recalc,
            )

            # Apply prompt tokens hint if we got one from metadata
            if (
                prompt_tokens_hint is not None
                and prompt_tokens_hint > 0
                and prompt_tokens_hint > usage_obj.prompt_tokens
            ):
                usage_obj = usage_obj.with_recalculated_tokens(
                    prompt_tokens=prompt_tokens_hint
                )
            usage = usage_obj.to_openrouter_dict()
        else:

            # Use existing usage, ensuring it's normalized
            usage = existing_usage

            # Still check if completion tokens need recalculation based on content
            completion_tokens = self._calculate_completion_tokens(payload, model_name)
            if completion_tokens is not None:
                existing_completion = int(usage.get("completion_tokens", 0) or 0)
                if self._should_replace_completion(
                    existing_completion, completion_tokens
                ):
                    if (
                        existing_completion != completion_tokens
                        and logger.isEnabledFor(logging.INFO)
                    ):
                        logger.info(
                            "Usage completion tokens recalculated: %s -> %s",
                            existing_completion,
                            completion_tokens,
                        )
                    usage["completion_tokens"] = completion_tokens
                    usage["total_tokens"] = (
                        usage.get("prompt_tokens", 0) + completion_tokens
                    )

        # Apply usage to envelope and payload
        usage_to_apply: dict[str, Any] | None = usage if usage else None

        if usage_to_apply:
            from src.core.domain.usage_summary import UsageSummary

            envelope.usage = UsageSummary.from_dict(usage_to_apply)
            if isinstance(payload, dict):
                payload["usage"] = usage_to_apply

        return payload, usage_to_apply

    def _normalize_usage_dict(self, usage: Any) -> dict[str, Any] | None:
        """Normalize a usage dictionary to OpenRouter-compatible format.

        Preserves extended fields (reasoning_tokens, cached_tokens, cost) when present.

        Args:
            usage: Usage to normalize

        Returns:
            Normalized usage dict or None
        """
        from src.core.domain.usage_summary import UsageSummary

        if isinstance(usage, UsageSummary):
            usage = usage.to_legacy_dict()
        if not isinstance(usage, dict):
            return None

        try:
            from src.core.domain.openrouter_usage import OpenRouterUsage

            parsed = OpenRouterUsage.from_dict(usage)
            if parsed is not None:
                return parsed.to_openrouter_dict()

            # Fallback to basic normalization
            return {
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            }
        except (ValueError, TypeError, KeyError, AttributeError):
            # Log at WARNING level since this is on a critical path for response formatting
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to normalize usage payload: %s", usage, exc_info=True
                )
            return None

    def _resolve_model_name(
        self, envelope: ResponseEnvelope, payload: Any
    ) -> str | None:
        """Extract model name from envelope metadata or payload.

        Args:
            envelope: Response envelope
            payload: Response payload

        Returns:
            Model name or None
        """
        if isinstance(payload, dict):
            model_name = payload.get("model") or payload.get("id")
            if isinstance(model_name, str) and model_name:
                return model_name

        metadata = getattr(envelope, "metadata", None)
        if isinstance(metadata, dict):
            model_name = metadata.get("model")
            if isinstance(model_name, str) and model_name:
                return model_name
        return None

    def _resolve_prompt_tokens(
        self, usage: dict[str, int] | None, envelope: ResponseEnvelope
    ) -> int | None:
        """Get prompt tokens from usage or outbound token metadata.

        Args:
            usage: Usage dictionary
            envelope: Response envelope

        Returns:
            Prompt tokens or None
        """
        if usage and isinstance(usage.get("prompt_tokens"), int):
            prompt_tokens = usage["prompt_tokens"]
            if prompt_tokens > 0:
                return prompt_tokens

        metadata = getattr(envelope, "metadata", None)
        if isinstance(metadata, dict):
            outbound_tokens = metadata.get("outbound_tokens")
            if isinstance(outbound_tokens, int | float):
                try:
                    return int(outbound_tokens)
                except (TypeError, ValueError):
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to coerce outbound_tokens: %s", outbound_tokens
                        )
        return None

    def _calculate_completion_tokens(
        self, payload: Any, model_name: str | None
    ) -> int | None:
        """Calculate completion tokens from the response payload.

        Args:
            payload: Response payload
            model_name: Optional model name

        Returns:
            Completion tokens or None
        """
        if count_tokens is None:
            return None

        text_value: str | None = None
        if isinstance(payload, dict):
            if should_recalculate_usage(payload):
                text_value = extract_content_text(payload)
        elif isinstance(payload, str):
            text_value = payload

        if text_value:
            try:
                return count_tokens(text_value, model=model_name)
            except (ValueError, TypeError, AttributeError):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Failed to calculate completion tokens", exc_info=True)
        return None

    def _should_replace_completion(
        self, existing_tokens: int, recalculated_tokens: int
    ) -> bool:
        """Decide if recalculated completion tokens should replace existing values.

        Args:
            existing_tokens: Existing token count
            recalculated_tokens: Recalculated token count

        Returns:
            True if should replace
        """
        if existing_tokens == 0:
            return True

        token_diff = abs(existing_tokens - recalculated_tokens)
        if token_diff > 10:
            return True

        try:
            return token_diff / existing_tokens > 0.05
        except ZeroDivisionError:
            # existing_tokens is 0 (shouldn't happen due to early return, but defensive)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Division by zero in _should_replace_completion (existing_tokens=0)",
                    exc_info=True,
                )
            return False
        except Exception as exc:
            # Log unexpected errors during token comparison
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Unexpected error in _should_replace_completion: %s",
                    exc,
                    exc_info=True,
                )
            return False

    def _sanitize_status_code(self, status_code: Any) -> int:
        """Sanitize status code to valid integer.

        Args:
            status_code: Status code to sanitize

        Returns:
            Sanitized status code (defaults to 200)
        """
        safe_status_code = 200
        if status_code is not None:
            if hasattr(status_code, "_mock_name") or hasattr(
                status_code, "_execute_mock_call"
            ):
                safe_status_code = 200
            else:
                try:
                    safe_status_code = int(status_code)
                except (TypeError, ValueError):
                    safe_status_code = 200
        return safe_status_code

    def _handle_backend_error_status_code(self, content: Any, status_code: int) -> int:
        """Handle backend error status code mapping.

        Args:
            content: Response content
            status_code: Status code

        Returns:
            Final status code
        """
        # Preserve original status code; specific error mappings are handled upstream
        return status_code

    def _create_json_response(
        self, content: Any, status_code: int, headers: dict[str, Any]
    ) -> JSONResponse:
        """Create JSONResponse with final sanitization.

        Args:
            content: Response content
            status_code: Status code
            headers: Response headers

        Returns:
            FastAPI JSONResponse
        """
        # CRITICAL: Apply steering leak protection as final safety net
        # This ensures internal steering data NEVER reaches clients
        if self._cached_steering_leak_protector is None:
            from src.core.services.steering_leak_protection import (
                get_steering_leak_protector,
            )

            self._cached_steering_leak_protector = get_steering_leak_protector()

        protector = self._cached_steering_leak_protector
        safe_content = content
        if protector.enabled and isinstance(content, dict):
            result = protector.sanitize_dict(content)
            safe_content = result.data
            if result.had_leak:
                logger.warning(
                    "SECURITY: Sanitized leaked steering data from non-streaming JSON response"
                )

        # Headers are already sanitized by HeaderSanitizer, but ensure they're filtered
        # Allow provider-specific headers for usage tracking and rate limiting
        allowed_prefixes = ("x-", "access-control-", "anthropic-", "openai-", "zenmux-")
        filtered_headers = {
            k: v
            for k, v in (headers or {}).items()
            if k.lower().startswith(allowed_prefixes)
        }

        response = JSONResponse(
            content=safe_content,
            status_code=status_code,
            media_type="application/json",
        )
        for key, value in filtered_headers.items():
            response.headers[key] = value
        return response
