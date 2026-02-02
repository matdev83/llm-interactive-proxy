"""
Structured output enforcer service.

This service applies structured output validation when a schema is present,
using the feature-first approach via StructuredOutputFeature (preferred) or
falling back to StructuredOutputMiddleware for legacy compatibility.

Requirements: 3.3, 5.5
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.backend_request_manager.context_models import (
    StructuredOutputContext,
)
from src.core.interfaces.backend_request_manager_components import (
    IStructuredOutputEnforcer,
)
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)


class StructuredOutputEnforcer(IStructuredOutputEnforcer):
    """Enforces structured output validation using feature-first approach."""

    def __init__(self, provider: IServiceProvider) -> None:
        """Initialize the structured output enforcer.

        Args:
            provider: Service provider for resolving StructuredOutputFeature or
                StructuredOutputMiddleware
        """
        self._provider = provider
        self._feature: Any | None = None
        self._middleware: Any | None = None

    def _get_feature(self) -> Any | None:
        """Get StructuredOutputFeature from provider (preferred path).

        Returns:
            StructuredOutputFeature instance or None if not available
        """
        if self._feature is not None:
            return self._feature

        try:
            from src.core.services.structured_output_middleware import (
                StructuredOutputFeature,
            )

            self._feature = self._provider.get_service(StructuredOutputFeature)
            return self._feature
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "StructuredOutputFeature not available: %s", e, exc_info=True
                )
            return None

    def _get_middleware(self) -> Any | None:
        """Get StructuredOutputMiddleware from provider (legacy fallback).

        Returns:
            StructuredOutputMiddleware instance or None if not available
        """
        if self._middleware is not None:
            return self._middleware

        try:
            from src.core.services.structured_output_middleware import (
                StructuredOutputMiddleware,
            )

            self._middleware = self._provider.get_service(StructuredOutputMiddleware)
            return self._middleware
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "StructuredOutputMiddleware not available: %s", e, exc_info=True
                )
            return None

    async def enforce(
        self,
        response: ProcessedResponse,
        context: StructuredOutputContext,
    ) -> ProcessedResponse:
        """Validate structured output and return a processed response.

        Args:
            response: The processed response to validate
            context: Structured output validation context

        Returns:
            A processed response with validated content

        Raises:
            ValidationError: If validation fails and strict mode is enabled
        """
        # Check if validation already happened (prevent double-processing)
        metadata = response.metadata or {}
        if metadata.get("structured_output_validated", False) or metadata.get(
            "schema_validation_attempted", False
        ):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Structured output validation already applied for request %s, skipping",
                    context.request_id,
                )
            return response

        # Try feature-first approach (preferred)
        feature = self._get_feature()
        if feature is not None:
            try:
                # Build context dict for feature.process
                # Respect strict_schema_validation from context if available
                strict_validation = True  # Default to strict
                if hasattr(context, "strict_schema_validation"):
                    strict_validation = getattr(context, "strict_schema_validation", True)  # type: ignore[attr-defined]
                elif isinstance(context, dict):
                    strict_validation = context.get("strict_schema_validation", True)

                feature_context: dict[str, Any] = {
                    "response_schema": context.response_schema,
                    "schema_name": context.schema_name,
                    "request_id": context.request_id,
                    "strict_schema_validation": strict_validation,
                }

                # Call feature's process_non_streaming method
                result = await feature.process_non_streaming(
                    response=response,
                    session_id=context.request_id,
                    context=feature_context,
                )

                # Ensure result is ProcessedResponse
                if isinstance(result, ProcessedResponse):
                    return result
                elif hasattr(result, "content") and hasattr(result, "metadata"):
                    return ProcessedResponse(
                        content=getattr(result, "content", response.content),
                        usage=getattr(result, "usage", response.usage),
                        metadata=getattr(result, "metadata", response.metadata),
                    )
                else:
                    # Fallback: wrap result in ProcessedResponse
                    return ProcessedResponse(
                        content=result if isinstance(result, str) else response.content,
                        usage=response.usage,
                        metadata=response.metadata,
                    )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "StructuredOutputFeature validation failed, trying legacy path: %s",
                        e,
                        exc_info=True,
                    )
                # Fall through to legacy middleware

        # Fallback to legacy middleware
        middleware = self._get_middleware()
        if middleware is not None:
            try:
                # Build context dict for middleware.process
                # Respect strict_schema_validation from context if available
                strict_validation = True  # Default to strict
                if hasattr(context, "strict_schema_validation"):
                    strict_validation = getattr(context, "strict_schema_validation", True)  # type: ignore[attr-defined]
                elif isinstance(context, dict):
                    strict_validation = context.get("strict_schema_validation", True)

                middleware_context: dict[str, Any] = {
                    "response_schema": context.response_schema,
                    "schema_name": context.schema_name,
                    "request_id": context.request_id,
                    "strict_schema_validation": strict_validation,
                }

                # Call middleware's process method
                result = await middleware.process(
                    response=response,
                    session_id=context.request_id,
                    context=middleware_context,
                    is_streaming=False,
                )

                # Ensure result is ProcessedResponse
                if isinstance(result, ProcessedResponse):
                    return result
                elif hasattr(result, "content") and hasattr(result, "metadata"):
                    return ProcessedResponse(
                        content=getattr(result, "content", response.content),
                        usage=getattr(result, "usage", response.usage),
                        metadata=getattr(result, "metadata", response.metadata),
                    )
                else:
                    # Fallback: wrap result in ProcessedResponse
                    return ProcessedResponse(
                        content=result if isinstance(result, str) else response.content,
                        usage=response.usage,
                        metadata=response.metadata,
                    )
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Structured output validation failed: %s",
                        e,
                        exc_info=True,
                    )
                raise

        # Neither feature nor middleware available
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Structured output validation requested but neither StructuredOutputFeature "
                "nor StructuredOutputMiddleware is available. Returning response unchanged."
            )
        return response
