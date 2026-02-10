"""Proxy-aware usage calculation service.

This service handles usage calculation and recalculation for the proxy,
accounting for content modifications that occur during request/response processing.

Key responsibilities:
1. Calculate usage when backends don't provide it
2. Recalculate usage when proxy modifies content (inbound or outbound)
3. Preserve extended usage fields (reasoning_tokens, cached_tokens, cost)
4. Ensure all responses include valid usage information
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from src.core.domain.openrouter_usage import (
    OpenRouterUsage,
)
from src.core.utils.token_count import (
    count_tokens,
    count_tokens_async,
    extract_prompt_text,
)

if TYPE_CHECKING:
    from src.core.domain.request_context import (
        ContentModificationTracker,
        RequestContext,
    )

logger = logging.getLogger(__name__)


# Global service instance for convenience
_usage_calculation_service: UsageCalculationService | None = None
_usage_calculation_service_lock = threading.Lock()


class UsageCalculationService:
    """Service for calculating and managing usage information.

    This service ensures accurate usage reporting by:
    1. Using backend-provided usage when available and unmodified
    2. Recalculating token counts when proxy modifications occur
    3. Calculating usage via tiktoken when backends don't provide it
    4. Preserving extended usage fields from backends
    """

    async def calculate_prompt_tokens_async(
        self,
        messages: list[Any],
        model: str | None = None,
    ) -> int:
        """Calculate prompt tokens from messages in a background thread."""
        try:
            prompt_text = extract_prompt_text(messages)
            return await count_tokens_async(prompt_text, model=model)
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to calculate prompt tokens async: %s", e, exc_info=True
                )
            return 0

    def calculate_prompt_tokens(
        self,
        messages: list[Any],
        model: str | None = None,
    ) -> int:
        """Calculate prompt tokens from messages.

        Args:
            messages: List of messages (OpenAI format or similar)
            model: Optional model name for encoding selection

        Returns:
            Number of prompt tokens
        """
        try:
            prompt_text = extract_prompt_text(messages)
            return count_tokens(prompt_text, model=model)
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to calculate prompt tokens: %s", e, exc_info=True
                )
            return 0

    async def calculate_completion_tokens_async(
        self,
        content: str | dict[str, Any] | Any,
        model: str | None = None,
    ) -> int:
        """Calculate completion tokens from response content in a background thread."""
        try:
            text = self._extract_completion_text(content)
            if not text:
                return 0
            return await count_tokens_async(text, model=model)
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to calculate completion tokens async: %s", e, exc_info=True
                )
            return 0

    def calculate_completion_tokens(
        self,
        content: str | dict[str, Any] | Any,
        model: str | None = None,
    ) -> int:
        """Calculate completion tokens from response content.

        Args:
            content: Response content (string or OpenAI-style dict)
            model: Optional model name for encoding selection

        Returns:
            Number of completion tokens
        """
        try:
            text = self._extract_completion_text(content)
            if not text:
                return 0
            return count_tokens(text, model=model)
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to calculate completion tokens: %s", e, exc_info=True
                )
            return 0

    def _extract_completion_text(self, content: Any) -> str:
        """Extract text content from various response formats.

        Args:
            content: Response content in various formats

        Returns:
            Extracted text content
        """
        if isinstance(content, str):
            return content

        if isinstance(content, dict):
            # Try OpenAI format: choices[0].message.content or choices[0].delta.content
            choices = content.get("choices", [])
            if choices and isinstance(choices, list):
                first_choice = choices[0] if choices else {}
                if isinstance(first_choice, dict):
                    # Non-streaming: message.content
                    message = first_choice.get("message", {})
                    if isinstance(message, dict) and message.get("content"):
                        return str(message["content"])

                    # Streaming: delta.content
                    delta = first_choice.get("delta", {})
                    if isinstance(delta, dict) and delta.get("content"):
                        return str(delta["content"])

            # Try direct content field
            if content.get("content"):
                return str(content["content"])

            # Try text field (Anthropic/other formats)
            if content.get("text"):
                return str(content["text"])

        # Try Pydantic model
        if hasattr(content, "model_dump") and not isinstance(content, dict):
            try:
                dumped = content.model_dump()  # type: ignore[attr-defined]
                return self._extract_completion_text(
                    dumped if isinstance(dumped, dict) else {}
                )
            except (AttributeError, TypeError, ValueError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to extract text from Pydantic model: %s",
                        e,
                        exc_info=True,
                    )

        return ""

    def calculate_usage_from_content(
        self,
        messages: list[Any] | None = None,
        response_content: Any = None,
        model: str | None = None,
    ) -> OpenRouterUsage:
        """Calculate complete usage from request messages and response content.

        Args:
            messages: Request messages (for prompt tokens)
            response_content: Response content (for completion tokens)
            model: Optional model name

        Returns:
            OpenRouterUsage with calculated tokens
        """
        prompt_tokens = 0
        completion_tokens = 0

        if messages:
            prompt_tokens = self.calculate_prompt_tokens(messages, model)

        if response_content:
            completion_tokens = self.calculate_completion_tokens(
                response_content, model
            )

        return OpenRouterUsage.from_basic_usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def should_recalculate_usage(
        self,
        backend_usage: dict[str, Any] | OpenRouterUsage | None,
        modification_tracker: ContentModificationTracker | None,
    ) -> bool:
        """Determine if usage should be recalculated.

        Recalculation is needed when:
        1. Backend didn't provide usage (or provided zeros)
        2. Content was modified during proxy processing

        Args:
            backend_usage: Usage provided by backend
            modification_tracker: Tracker with modification flags

        Returns:
            True if usage should be recalculated
        """
        # Always recalculate if no usage provided
        if backend_usage is None:
            return True

        # Check if backend usage has valid values
        if isinstance(backend_usage, OpenRouterUsage):
            if (
                backend_usage.prompt_tokens == 0
                and backend_usage.completion_tokens == 0
            ):
                return True
        else:
            prompt = backend_usage.get("prompt_tokens", 0) or 0
            completion = backend_usage.get("completion_tokens", 0) or 0
            if prompt == 0 and completion == 0:
                return True

        # Recalculate if content was modified
        if modification_tracker is not None:
            return modification_tracker.requires_usage_recalculation()

        return False

    def _adjust_tokens_with_delta(
        self,
        *,
        base_tokens: int | None,
        original_tokens: int | None,
        modified_tokens: int,
    ) -> int:
        """Adjust backend-reported tokens using proxy-observed deltas.

        When we have both original and modified token counts from proxy-side
        transformations, apply only the delta to backend usage so backend remains
        the source of truth.
        """
        if base_tokens is not None and original_tokens is not None:
            delta = modified_tokens - original_tokens
            return max(base_tokens + delta, 0)
        return max(modified_tokens, 0)

    def recalculate_usage(
        self,
        backend_usage: dict[str, Any] | OpenRouterUsage | None,
        modification_tracker: ContentModificationTracker | None,
        messages: list[Any] | None = None,
        response_content: Any = None,
        model: str | None = None,
        force_recalculation: bool = False,
    ) -> OpenRouterUsage:
        """Recalculate usage accounting for proxy modifications.

        This method preserves extended usage fields (reasoning_tokens, cached_tokens, cost)
        while recalculating the base token counts when needed.

        Args:
            backend_usage: Original usage from backend
            modification_tracker: Tracker with modification details
            messages: Request messages (after proxy modifications)
            response_content: Response content (after proxy modifications)
            model: Model name for tokenization
            force_recalculation: Force recalculation even without modification tracker

        Returns:
            OpenRouterUsage with recalculated values
        """
        # Parse backend usage if provided
        base_usage: OpenRouterUsage | None = None
        if backend_usage is not None:
            if isinstance(backend_usage, OpenRouterUsage):
                base_usage = backend_usage
            else:
                base_usage = OpenRouterUsage.from_dict(backend_usage)

        # Calculate new token counts
        new_prompt_tokens: int | None = None
        new_completion_tokens: int | None = None

        # Recalculate prompt tokens if inbound was modified
        if modification_tracker is not None and modification_tracker.inbound_modified:
            if modification_tracker.inbound_modified_tokens is not None:
                new_prompt_tokens = self._adjust_tokens_with_delta(
                    base_tokens=base_usage.prompt_tokens if base_usage else None,
                    original_tokens=modification_tracker.inbound_original_tokens,
                    modified_tokens=modification_tracker.inbound_modified_tokens,
                )
            elif messages:
                recalculated_prompt_tokens = self.calculate_prompt_tokens(
                    messages, model
                )
                new_prompt_tokens = self._adjust_tokens_with_delta(
                    base_tokens=base_usage.prompt_tokens if base_usage else None,
                    original_tokens=modification_tracker.inbound_original_tokens,
                    modified_tokens=recalculated_prompt_tokens,
                )

            if logger.isEnabledFor(logging.DEBUG):
                original = (
                    modification_tracker.inbound_original_tokens
                    if modification_tracker.inbound_original_tokens is not None
                    else (base_usage.prompt_tokens if base_usage else 0)
                )
                logger.debug(
                    "Recalculated prompt tokens due to inbound modification: %d -> %d "
                    "(reasons: %s)",
                    original,
                    new_prompt_tokens or 0,
                    ", ".join(modification_tracker.inbound_modification_reasons),
                )

        # Recalculate completion tokens if outbound was modified OR forced
        should_recalc_completion = force_recalculation or (
            modification_tracker is not None and modification_tracker.outbound_modified
        )

        if should_recalc_completion:
            if (
                modification_tracker is not None
                and modification_tracker.outbound_modified_tokens is not None
            ):
                new_completion_tokens = self._adjust_tokens_with_delta(
                    base_tokens=base_usage.completion_tokens if base_usage else None,
                    original_tokens=modification_tracker.outbound_original_tokens,
                    modified_tokens=modification_tracker.outbound_modified_tokens,
                )
            elif response_content:
                recalculated_completion_tokens = self.calculate_completion_tokens(
                    response_content, model
                )
                new_completion_tokens = self._adjust_tokens_with_delta(
                    base_tokens=base_usage.completion_tokens if base_usage else None,
                    original_tokens=(
                        modification_tracker.outbound_original_tokens
                        if modification_tracker is not None
                        else None
                    ),
                    modified_tokens=recalculated_completion_tokens,
                )

            if logger.isEnabledFor(logging.DEBUG):
                original = (
                    modification_tracker.outbound_original_tokens
                    if modification_tracker is not None
                    and modification_tracker.outbound_original_tokens is not None
                    else (base_usage.completion_tokens if base_usage else 0)
                )
                reasons = (
                    modification_tracker.outbound_modification_reasons
                    if modification_tracker is not None
                    else ["forced_recalculation"]
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Recalculated completion tokens: %d -> %d (reasons: %s)",
                        original,
                        new_completion_tokens or 0,
                        ", ".join(reasons),
                    )

        # If we have base usage, update only the modified fields
        if base_usage is not None:
            return base_usage.with_recalculated_tokens(
                prompt_tokens=new_prompt_tokens,
                completion_tokens=new_completion_tokens,
            )

        # No base usage - calculate everything from scratch
        prompt = new_prompt_tokens
        if prompt is None and messages:
            prompt = self.calculate_prompt_tokens(messages, model)

        completion = new_completion_tokens
        if completion is None and response_content:
            completion = self.calculate_completion_tokens(response_content, model)

        return OpenRouterUsage.from_basic_usage(
            prompt_tokens=prompt or 0,
            completion_tokens=completion or 0,
        )

    def ensure_usage(
        self,
        backend_usage: dict[str, Any] | OpenRouterUsage | None,
        context: RequestContext | None = None,
        messages: list[Any] | None = None,
        response_content: Any = None,
        model: str | None = None,
        force_recalculation: bool = False,
    ) -> OpenRouterUsage:
        """Ensure usage information is present and accurate.

        This is the main entry point for ensuring responses include valid usage.
        It handles:
        1. Using backend usage when available and unmodified
        2. Recalculating when modifications occurred
        3. Calculating from scratch when needed

        Args:
            backend_usage: Usage provided by backend (if any)
            context: Request context with modification tracker
            messages: Request messages (after transformations)
            response_content: Response content (after transformations)
            model: Model name for tokenization
            force_recalculation: Force recalculation even without modifications

        Returns:
            OpenRouterUsage instance
        """
        # Get modification tracker from context
        modification_tracker = None
        if context is not None and context.processing_context is not None:
            modification_tracker = context.processing_context.modification_tracker

        # Determine if recalculation is needed
        needs_recalculation = force_recalculation or self.should_recalculate_usage(
            backend_usage, modification_tracker
        )

        if needs_recalculation:
            usage = self.recalculate_usage(
                backend_usage=backend_usage,
                modification_tracker=modification_tracker,
                messages=messages,
                response_content=response_content,
                model=model,
                force_recalculation=force_recalculation,
            )
        else:
            # Use backend usage as-is (parsing to normalize format)
            if isinstance(backend_usage, OpenRouterUsage):
                usage = backend_usage
            elif backend_usage is not None:
                parsed = OpenRouterUsage.from_dict(backend_usage)
                usage = parsed if parsed else OpenRouterUsage()
            else:
                usage = OpenRouterUsage()

        return usage

    def merge_streaming_usage(
        self,
        accumulated_content: str,
        final_chunk_usage: dict[str, Any] | None,
        context: RequestContext | None = None,
        model: str | None = None,
        force_recalculation: bool = False,
    ) -> OpenRouterUsage:
        """Merge usage for streaming responses.

        For streaming responses, the final chunk may contain usage information
        but may not account for proxy modifications during streaming.

        Args:
            accumulated_content: All accumulated content from stream
            final_chunk_usage: Usage from final streaming chunk
            context: Request context with modification tracker
            model: Model name
            force_recalculation: Force recalculation even without modification flags

        Returns:
            OpenRouterUsage with merged values
        """
        # Parse final chunk usage
        base_usage = (
            OpenRouterUsage.from_dict(final_chunk_usage) if final_chunk_usage else None
        )

        # Get modification tracker
        modification_tracker = None
        if context is not None and context.processing_context is not None:
            modification_tracker = context.processing_context.modification_tracker

        # Check if outbound modifications require recalculation
        should_force_recalc = force_recalculation or (
            modification_tracker is not None and modification_tracker.outbound_modified
        )

        if should_force_recalc:
            if not accumulated_content and base_usage is not None:
                return base_usage

            # Recalculate completion tokens from accumulated content
            completion_tokens = self.calculate_completion_tokens(
                accumulated_content, model
            )

            if base_usage is not None:
                result = base_usage.with_recalculated_tokens(
                    completion_tokens=completion_tokens
                )
            else:
                result = OpenRouterUsage.from_basic_usage(
                    prompt_tokens=0,
                    completion_tokens=completion_tokens,
                )

            if logger.isEnabledFor(logging.DEBUG):
                reasons = (
                    ", ".join(modification_tracker.outbound_modification_reasons)
                    if modification_tracker is not None
                    else "unknown"
                )
                logger.debug(
                    "Merged streaming usage with outbound modifications: "
                    "completion_tokens=%d (reasons: %s)",
                    completion_tokens,
                    reasons,
                )

            return result

        # No modifications - use final chunk usage or calculate
        if base_usage is not None:
            return base_usage

        # No usage provided - calculate from accumulated content
        completion_tokens = self.calculate_completion_tokens(accumulated_content, model)
        return OpenRouterUsage.from_basic_usage(completion_tokens=completion_tokens)


def get_usage_calculation_service() -> UsageCalculationService:
    """Get or create the global usage calculation service instance."""
    global _usage_calculation_service
    if _usage_calculation_service is None:
        # Use threading.Lock with double-checked locking for lazy initialization
        # NOTE: threading.Lock is safe here because:
        # 1. After initialization, the fast path has no lock (simple read)
        # 2. The critical section is minimal (only __init__, no I/O or blocking ops)
        # 3. The class is pure Python with no external dependencies during init
        with _usage_calculation_service_lock:
            if _usage_calculation_service is None:
                _usage_calculation_service = UsageCalculationService()
    return _usage_calculation_service
