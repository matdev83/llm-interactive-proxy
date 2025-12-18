"""Mixin for automatic usage calculation in backend connectors.

This mixin ensures that all backend connectors return usage information,
either from the backend response or calculated using tiktoken.

Updated to integrate with the new UsageCalculationService and support
OpenRouter-compatible extended usage fields.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.core.domain.openrouter_usage import OpenRouterUsage

if TYPE_CHECKING:
    from src.core.domain.responses import ResponseEnvelope

logger = logging.getLogger(__name__)


class UsageCalculationMixin:
    """Mixin to ensure usage is always present in responses.

    This mixin provides automatic usage calculation for connectors that
    may not receive usage information from their backend APIs.

    Features:
    1. Calculates usage via tiktoken when backends don't provide it
    2. Preserves extended usage fields (reasoning_tokens, cached_tokens, cost)
    3. Integrates with UsageCalculationService for consistent behavior
    """

    def ensure_usage_in_response(
        self,
        response_envelope: ResponseEnvelope,
        request_messages: list[Any],
        model_name: str,
    ) -> ResponseEnvelope:
        """Ensure usage information is present in the response envelope.

        If usage is missing or has zero values, calculates it using tiktoken.
        Preserves extended usage fields from backends when available.

        Args:
            response_envelope: The response from the backend
            request_messages: The original request messages
            model_name: The model name used for the request

        Returns:
            ResponseEnvelope with usage information in OpenRouter format
        """
        # Parse existing usage to check if calculation is needed
        existing_usage = None
        if response_envelope.usage:
            existing_usage = OpenRouterUsage.from_dict(
                response_envelope.usage.to_legacy_dict()
            )

        # Check if usage needs to be calculated
        should_calculate = False

        if existing_usage is None:
            should_calculate = True
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "No usage information in response from %s, will calculate",
                    model_name,
                )
        else:
            # Check for zero values in basic fields
            if (
                existing_usage.prompt_tokens == 0
                and existing_usage.completion_tokens == 0
            ):
                should_calculate = True
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Zero usage values detected in response from %s, will calculate",
                        model_name,
                    )

        if should_calculate:
            calculated_usage = self._calculate_usage_from_content(
                response_envelope, request_messages, model_name, existing_usage
            )
            from src.core.domain.usage_summary import UsageSummary

            response_envelope.usage = UsageSummary.from_dict(calculated_usage)
        elif existing_usage is not None:
            # Normalize existing usage to OpenRouter format
            from src.core.domain.usage_summary import UsageSummary

            response_envelope.usage = UsageSummary.from_dict(
                existing_usage.to_openrouter_dict()
            )

        return response_envelope

    def _calculate_usage_from_content(
        self,
        response_envelope: ResponseEnvelope,
        request_messages: list[Any],
        model_name: str,
        base_usage: OpenRouterUsage | None = None,
    ) -> dict[str, Any]:
        """Calculate token usage from request and response content.

        This calculates tokens based on what was ACTUALLY sent/received,
        accounting for any proxy transformations. Preserves extended fields
        from base_usage when provided.

        Args:
            response_envelope: The response envelope
            request_messages: The request messages (after transformations)
            model_name: The model name
            base_usage: Optional existing usage with extended fields to preserve

        Returns:
            Dictionary with usage in OpenRouter format
        """
        from src.core.services.usage_calculation_service import (
            get_usage_calculation_service,
        )

        service = get_usage_calculation_service()

        try:
            # Calculate prompt tokens from ACTUAL messages sent to backend
            prompt_tokens = service.calculate_prompt_tokens(
                request_messages, model_name
            )

            # Calculate completion tokens from response content
            completion_tokens = service.calculate_completion_tokens(
                response_envelope.content, model_name
            )

            # Create usage, preserving extended fields from base if available
            if base_usage is not None:
                calculated_usage = base_usage.with_recalculated_tokens(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            else:
                calculated_usage = OpenRouterUsage.from_basic_usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Calculated usage for %s: prompt=%d, completion=%d, total=%d",
                    model_name,
                    calculated_usage.prompt_tokens,
                    calculated_usage.completion_tokens,
                    calculated_usage.total_tokens,
                )

            return calculated_usage.to_openrouter_dict()

        except (ValueError, TypeError, AttributeError):
            logger.warning(
                "Failed to calculate usage for %s", model_name, exc_info=True
            )
            # Return zero usage as fallback
            return OpenRouterUsage().to_openrouter_dict()

    def merge_backend_usage(
        self,
        backend_usage: dict[str, Any] | None,
        calculated_prompt_tokens: int | None = None,
        calculated_completion_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Merge backend-provided usage with calculated values.

        Useful when backend provides some usage info but not all fields.
        Preserves extended fields from backend while filling in missing basics.

        Args:
            backend_usage: Usage dict from backend (may have extended fields)
            calculated_prompt_tokens: Optional calculated prompt tokens
            calculated_completion_tokens: Optional calculated completion tokens

        Returns:
            Merged usage dictionary in OpenRouter format
        """
        # Parse backend usage
        base = OpenRouterUsage.from_dict(backend_usage) if backend_usage else None

        if base is None:
            # No backend usage - use calculated values
            return OpenRouterUsage.from_basic_usage(
                prompt_tokens=calculated_prompt_tokens or 0,
                completion_tokens=calculated_completion_tokens or 0,
            ).to_openrouter_dict()

        # Fill in missing values with calculated ones
        prompt = base.prompt_tokens
        if prompt == 0 and calculated_prompt_tokens:
            prompt = calculated_prompt_tokens

        completion = base.completion_tokens
        if completion == 0 and calculated_completion_tokens:
            completion = calculated_completion_tokens

        return base.with_recalculated_tokens(
            prompt_tokens=prompt if prompt != base.prompt_tokens else None,
            completion_tokens=(
                completion if completion != base.completion_tokens else None
            ),
        ).to_openrouter_dict()
