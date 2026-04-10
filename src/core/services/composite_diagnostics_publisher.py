"""Structured diagnostics publisher for composite routing flows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast

from pydantic.types import JsonValue

from src.core.domain.backend_target import BackendTarget
from src.core.domain.composite_routing import (
    CompositeSelectorValidationError,
    RoutingSurface,
)
from src.core.domain.request_context import RequestContext
from src.core.services.composite_routing_state import contains_top_level_operator

COMPOSITE_ROUTING_DIAGNOSTICS_KEY = "composite_routing_diagnostics"

__all__ = ["COMPOSITE_ROUTING_DIAGNOSTICS_KEY", "CompositeDiagnosticsPublisher"]


class CompositeDiagnosticsPublisher:
    """Publishes operator-actionable diagnostics into request context extensions."""

    def should_publish(
        self,
        *,
        selector: str,
        surface: RoutingSurface,
    ) -> bool:
        return (
            contains_top_level_operator(selector, "|")
            or contains_top_level_operator(selector, "^")
            or (surface is RoutingSurface.REPLACEMENT_BRIDGE)
        )

    def publish_validation_error(
        self,
        *,
        context: RequestContext | None,
        selector: str,
        surface: RoutingSurface,
        error: CompositeSelectorValidationError,
    ) -> None:
        diagnostics = self._ensure_payload(
            context=context,
            selector=selector,
            surface=surface,
        )
        if diagnostics is None:
            return
        diagnostics["error"] = {
            "code": "routing_validation_failed",
            "message": error.message,
            "validation": error.envelope.model_dump(mode="json"),
        }
        self._persist(context=context, payload=diagnostics)

    def publish_selected_target(
        self,
        *,
        context: RequestContext | None,
        selector: str,
        surface: RoutingSurface,
        selected_selector: str,
        target: BackendTarget,
        branch_history: Iterable[Mapping[str, JsonValue]] | None = None,
        branch_history_omitted: int | None = None,
    ) -> None:
        diagnostics = self._ensure_payload(
            context=context,
            selector=selector,
            surface=surface,
        )
        if diagnostics is None:
            return
        selected_target: dict[str, JsonValue] = {
            "selector": selected_selector,
            "backend": target.backend,
            "model": target.model,
        }
        if target.uri_params:
            selected_target["uri_params"] = cast(JsonValue, dict(target.uri_params))
        diagnostics["selected_target"] = selected_target
        if branch_history is not None:
            diagnostics["branch_history"] = cast(
                JsonValue,
                self._normalize_branch_history(branch_history),
            )
            if branch_history_omitted is not None and branch_history_omitted > 0:
                diagnostics["branch_history_omitted"] = branch_history_omitted
        self._persist(context=context, payload=diagnostics)

    def publish_exhaustion(
        self,
        *,
        context: RequestContext | None,
        selector: str,
        surface: RoutingSurface,
        reason: str,
        details: Mapping[str, JsonValue] | None = None,
        branch_history: Iterable[Mapping[str, JsonValue]] | None = None,
        branch_history_omitted: int | None = None,
    ) -> None:
        diagnostics = self._ensure_payload(
            context=context,
            selector=selector,
            surface=surface,
        )
        if diagnostics is None:
            return
        exhaustion: dict[str, JsonValue] = {"reason": reason}
        if details:
            for key, value in details.items():
                if isinstance(key, str):
                    exhaustion[key] = value
        diagnostics["exhaustion"] = exhaustion
        if branch_history is not None:
            diagnostics["branch_history"] = cast(
                JsonValue,
                self._normalize_branch_history(branch_history),
            )
            if branch_history_omitted is not None and branch_history_omitted > 0:
                diagnostics["branch_history_omitted"] = branch_history_omitted
        self._persist(context=context, payload=diagnostics)

    @staticmethod
    def _normalize_branch_history(
        branch_history: Iterable[Mapping[str, JsonValue]],
    ) -> list[dict[str, JsonValue]]:
        normalized: list[dict[str, JsonValue]] = []
        for item in branch_history:
            normalized_item: dict[str, JsonValue] = {}
            for key, value in item.items():
                if isinstance(key, str):
                    normalized_item[key] = value
            normalized.append(normalized_item)
        return normalized

    @staticmethod
    def _ensure_payload(
        *,
        context: RequestContext | None,
        selector: str,
        surface: RoutingSurface,
    ) -> dict[str, JsonValue] | None:
        if context is None:
            return None
        existing = context.extensions.get(COMPOSITE_ROUTING_DIAGNOSTICS_KEY)
        payload: dict[str, JsonValue]
        if isinstance(existing, dict):
            payload = {
                key: value for key, value in existing.items() if isinstance(key, str)
            }
        else:
            payload = {}
        payload["surface"] = surface.value
        payload["selector"] = selector
        return payload

    @staticmethod
    def _persist(
        *,
        context: RequestContext | None,
        payload: Mapping[str, Any],
    ) -> None:
        if context is None:
            return
        context.extensions[COMPOSITE_ROUTING_DIAGNOSTICS_KEY] = {
            key: value for key, value in payload.items() if isinstance(key, str)
        }
