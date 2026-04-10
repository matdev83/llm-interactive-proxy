"""Shared entry point for composite selector routing execution."""

from __future__ import annotations

import logging
from typing import Protocol

from src.core.common.exceptions import RoutingError
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatRequest
from src.core.domain.composite_routing import (
    CompositeRoutePlan,
    CompositeRoutingInput,
    CompositeSelectorValidationError,
)
from src.core.domain.request_context import RequestContext
from src.core.services.composite_diagnostics_publisher import (
    CompositeDiagnosticsPublisher,
)

logger = logging.getLogger(__name__)

__all__ = ["CompositeRoutingService"]


class _CompositeParser(Protocol):
    def parse(self, routing_input: CompositeRoutingInput) -> CompositeRoutePlan: ...


class _CompositeCoordinator(Protocol):
    async def execute(
        self,
        *,
        plan: CompositeRoutePlan,
        routing_input: CompositeRoutingInput,
        request: ChatRequest,
        context: RequestContext | None,
    ) -> BackendTarget: ...


class CompositeRoutingService:
    """Parses and executes composite selectors using shared coordinator logic."""

    def __init__(
        self,
        *,
        parser: _CompositeParser,
        coordinator: _CompositeCoordinator,
        diagnostics_publisher: CompositeDiagnosticsPublisher | None = None,
    ):
        self._parser = parser
        self._coordinator = coordinator
        self._diagnostics_publisher = (
            diagnostics_publisher or CompositeDiagnosticsPublisher()
        )

    async def resolve_target(
        self,
        *,
        routing_input: CompositeRoutingInput,
        request: ChatRequest,
        context: RequestContext | None,
    ) -> BackendTarget:
        should_publish = self._diagnostics_publisher.should_publish(
            selector=routing_input.selector,
            surface=routing_input.surface,
        )
        try:
            plan = self._parser.parse(routing_input)
        except CompositeSelectorValidationError as validation_error:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Composite selector validation failed: surface=%s selector=%s error=%s",
                    routing_input.surface.value,
                    routing_input.selector,
                    validation_error.message,
                )
            self._diagnostics_publisher.publish_validation_error(
                context=context,
                selector=routing_input.selector,
                surface=routing_input.surface,
                error=validation_error,
            )
            raise

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Composite selector parsed: surface=%s node_kind=%s selector=%s",
                routing_input.surface.value,
                plan.root_node.kind,
                plan.normalized_selector,
            )

        try:
            return await self._coordinator.execute(
                plan=plan,
                routing_input=routing_input,
                request=request,
                context=context,
            )
        except RoutingError as routing_error:
            if should_publish:
                self._publish_routing_error_diagnostics(
                    context=context,
                    routing_input=routing_input,
                    routing_error=routing_error,
                )
            raise

    def _publish_routing_error_diagnostics(
        self,
        *,
        context: RequestContext | None,
        routing_input: CompositeRoutingInput,
        routing_error: RoutingError,
    ) -> None:
        details = (
            routing_error.details if isinstance(routing_error.details, dict) else {}
        )
        reason = details.get("reason")
        if not isinstance(reason, str) or not reason:
            return
        if reason not in {"attempt_budget_exhausted", "failover_exhausted"}:
            return
        normalized_details = {
            key: value for key, value in details.items() if isinstance(key, str)
        }
        self._diagnostics_publisher.publish_exhaustion(
            context=context,
            selector=routing_input.selector,
            surface=routing_input.surface,
            reason=reason,
            details=normalized_details,
        )
