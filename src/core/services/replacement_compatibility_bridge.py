"""Compatibility bridge from legacy random replacement to composite routing."""

from __future__ import annotations

import logging

from src.core.common.exceptions import ValidationError
from src.core.domain.model_utils import has_explicit_backend_selector
from src.core.domain.request_context import RequestContext
from src.core.services.composite_routing_state import contains_top_level_operator

logger = logging.getLogger(__name__)

__all__ = ["ReplacementCompatibilityBridge"]

_REMOVAL_TIMELINE = "N+1"
_DEPRECATION_EXTENSION_KEY = "replacement_deprecation"
_REPLACEMENT_EFFECTIVE_SESSION_ID_KEY = "replacement_effective_session_id"
_REPLACEMENT_SOURCE_SELECTOR_KEY = "replacement_source_selector"
_REPLACEMENT_EFFECTIVE_SELECTOR_KEY = "replacement_effective_selector"


class ReplacementCompatibilityBridge:
    """Validate replacement selectors and emit migration deprecation metadata."""

    def translate_selector(
        self,
        *,
        selector: str,
        context: RequestContext | None,
    ) -> str:
        normalized_selector = selector.strip()
        self._validate_single_target_selector(normalized_selector)

        effective_session_id = self._resolve_effective_session_id(context)
        source_selector = self._resolve_optional_selector_hint(
            context=context,
            key=_REPLACEMENT_SOURCE_SELECTOR_KEY,
        )
        effective_selector = self._resolve_optional_selector_hint(
            context=context,
            key=_REPLACEMENT_EFFECTIVE_SELECTOR_KEY,
        )
        if source_selector is not None:
            self._validate_single_target_selector(source_selector)
        if effective_selector is not None:
            self._validate_single_target_selector(effective_selector)
        resolved_effective_selector = effective_selector or normalized_selector
        translated_selector = self._build_weighted_selector(resolved_effective_selector)
        self._publish_deprecation_metadata(
            context=context,
            source_selector=normalized_selector,
            source_hint=source_selector,
            effective_selector=resolved_effective_selector,
            translated_selector=translated_selector,
            effective_session_id=effective_session_id,
        )
        return translated_selector

    @staticmethod
    def _validate_single_target_selector(selector: str) -> None:
        if contains_top_level_operator(selector, "|") or contains_top_level_operator(
            selector, "^"
        ):
            raise ValidationError(
                message=(
                    "Unsupported replacement mapping. Replacement bridge accepts only "
                    "single-target selectors for migration safety."
                ),
                details={
                    "code": "replacement_migration_required",
                    "reason": "unsupported_replacement_mapping",
                    "selector": selector,
                    "expected_format": "<backend>:<model>",
                },
            )

        if not has_explicit_backend_selector(selector):
            raise ValidationError(
                message=(
                    "Replacement bridge requires explicit backend:model selector "
                    "for deterministic migration."
                ),
                details={
                    "code": "replacement_migration_required",
                    "reason": "explicit_backend_required",
                    "selector": selector,
                    "expected_format": "<backend>:<model>",
                },
            )

    @staticmethod
    def _resolve_optional_selector_hint(
        *,
        context: RequestContext | None,
        key: str,
    ) -> str | None:
        if context is None:
            return None
        raw_value = context.extensions.get(key)
        if isinstance(raw_value, str):
            normalized = raw_value.strip()
            if normalized:
                return normalized
        return None

    @staticmethod
    def _build_weighted_selector(selector: str) -> str:
        # Equivalent deterministic weighted translation: both branches resolve to
        # the same explicit selector, preserving current replacement behavior.
        return f"[weight=1]{selector}^[weight=1]{selector}"

    @staticmethod
    def _resolve_effective_session_id(context: RequestContext | None) -> str:
        if context is None:
            raise ValidationError(
                message=(
                    "Replacement bridge requires replacement_effective_session_id "
                    "for deterministic migration."
                ),
                details={
                    "code": "replacement_migration_required",
                    "reason": "missing_effective_session_id",
                },
            )

        raw_value = context.extensions.get(_REPLACEMENT_EFFECTIVE_SESSION_ID_KEY)
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()

        raise ValidationError(
            message=(
                "Replacement bridge requires replacement_effective_session_id "
                "for deterministic migration."
            ),
            details={
                "code": "replacement_migration_required",
                "reason": "missing_effective_session_id",
            },
        )

    @staticmethod
    def _publish_deprecation_metadata(
        *,
        context: RequestContext | None,
        source_selector: str,
        source_hint: str | None,
        effective_selector: str,
        translated_selector: str,
        effective_session_id: str,
    ) -> None:
        if context is None:
            return

        context.extensions[_DEPRECATION_EXTENSION_KEY] = {
            "status": "deprecated",
            "feature": "random_model_replacement",
            "compatibility_bridge": "replacement_compatibility_bridge",
            "removal_timeline": _REMOVAL_TIMELINE,
            "effective_session_id": effective_session_id,
            "source_selector": source_selector,
            "source_selector_hint": source_hint,
            "effective_selector": effective_selector,
            "translated_selector": translated_selector,
            "migration_hint": (
                "Migrate replacement rules to explicit composite selectors with "
                "weighted branches."
            ),
        }

        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Random model replacement compatibility bridge is active; "
                "this path will be removed in %s.",
                _REMOVAL_TIMELINE,
            )
