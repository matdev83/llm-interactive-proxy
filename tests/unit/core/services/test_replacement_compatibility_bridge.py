from __future__ import annotations

import pytest
from src.core.common.exceptions import ValidationError
from src.core.domain.request_context import RequestContext
from src.core.services.replacement_compatibility_bridge import (
    ReplacementCompatibilityBridge,
)


def _context() -> RequestContext:
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-replacement-bridge",
        session_id="session-replacement-bridge",
    )
    context.extensions["replacement_effective_session_id"] = "replacement-session-1"
    return context


def test_translate_selector_returns_weighted_composite_for_safe_replacement() -> None:
    bridge = ReplacementCompatibilityBridge()
    context = _context()

    translated = bridge.translate_selector(
        selector="openai:gpt-4o-mini",
        context=context,
    )

    assert translated == "openai:gpt-4o-mini"
    deprecation = context.extensions.get("replacement_deprecation")
    assert isinstance(deprecation, dict)
    assert deprecation.get("removal_timeline") == "N+1"
    assert deprecation.get("effective_session_id") == "replacement-session-1"


@pytest.mark.parametrize(
    "selector",
    [
        "openai:gpt-4o-mini|anthropic:claude-3-5-sonnet",
        "openai:gpt-4o-mini^anthropic:claude-3-5-sonnet",
    ],
)
def test_translate_selector_rejects_preexisting_composite_selector(
    selector: str,
) -> None:
    bridge = ReplacementCompatibilityBridge()

    with pytest.raises(ValidationError) as exc_info:
        bridge.translate_selector(
            selector=selector,
            context=_context(),
        )

    assert "unsupported replacement mapping" in str(exc_info.value).lower()


def test_translate_selector_rejects_selector_without_explicit_backend() -> None:
    bridge = ReplacementCompatibilityBridge()

    with pytest.raises(ValidationError) as exc_info:
        bridge.translate_selector(
            selector="gpt-4o-mini",
            context=_context(),
        )

    assert "explicit backend" in str(exc_info.value).lower()


def test_translate_selector_requires_stable_replacement_identity() -> None:
    bridge = ReplacementCompatibilityBridge()
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
    )

    with pytest.raises(ValidationError) as exc_info:
        bridge.translate_selector(
            selector="openai:gpt-4o-mini",
            context=context,
        )

    assert "replacement_effective_session_id" in str(exc_info.value)
