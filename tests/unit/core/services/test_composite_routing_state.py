from __future__ import annotations

from src.core.domain.composite_routing import RoutingSurface
from src.core.domain.request_context import RequestContext
from src.core.services.composite_routing_state import (
    COMPOSITE_ROUTING_SURFACE_KEY,
    resolve_composite_routing_surface,
)


def _context_with_extensions(**extensions: str) -> RequestContext:
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-composite-state",
        session_id="sess-composite-state",
    )
    for key, value in extensions.items():
        context.extensions[key] = value
    return context


def test_quality_verifier_call_purpose_overrides_stale_surface_hint() -> None:
    context = _context_with_extensions(
        **{
            COMPOSITE_ROUTING_SURFACE_KEY: RoutingSurface.AUXILIARY.value,
            "call_purpose": "quality_verifier",
        }
    )

    resolved = resolve_composite_routing_surface(context)

    assert resolved is RoutingSurface.QUALITY_VERIFIER


def test_quality_verifier_prefixed_call_purpose_overrides_stale_surface_hint() -> None:
    context = _context_with_extensions(
        **{
            COMPOSITE_ROUTING_SURFACE_KEY: RoutingSurface.MAIN.value,
            "call_purpose": "quality_verifier_steering_recall",
        }
    )

    resolved = resolve_composite_routing_surface(context)

    assert resolved is RoutingSurface.QUALITY_VERIFIER
