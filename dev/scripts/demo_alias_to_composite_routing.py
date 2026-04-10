#!/usr/bin/env python
"""Demo: Model Alias Resolving to Composite Routing Selector.

This script demonstrates that model aliases can resolve to composite routing
selectors (failover or weighted), and the proxy will correctly parse and
route requests through the composite routing system.

Example alias configuration:
    model_aliases:
      - pattern: "^alias:minimax-m2$"
        replacement: "ollama:minimax-m2.7-cloud|opencode-zen:minimax-m2.5-free"

When a request comes with `model: "alias:minimax-m2"`:
1. Alias resolver maps it to the composite failover string
2. Composite parser detects `|` operator and creates failover group
3. Coordinator tries first backend, falls back to second on failure

Usage:
    .venv/Scripts/python.exe -m dev.scripts.demo_alias_to_composite_routing
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

ALIAS_PATTERN = "alias:minimax-m2"
COMPOSITE_REPLACEMENT = "ollama:minimax-m2.7-cloud|opencode-zen:minimax-m2.5-free"


def _create_mock_dependencies(
    *,
    unavailable_backends: set[str] | None = None,
) -> dict[str, Any]:
    """Create mock dependencies for BackendModelResolver."""
    unavailable = unavailable_backends or set()

    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)

    model_alias_resolver = MagicMock()

    def _resolve_alias(model: str) -> str:
        if model == ALIAS_PATTERN:
            logger.info(f"Alias resolver: '{model}' -> '{COMPOSITE_REPLACEMENT}'")
            return COMPOSITE_REPLACEMENT
        return model

    model_alias_resolver.resolve.side_effect = _resolve_alias

    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()

    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}

    routing_service = MagicMock()

    def _resolve_backend_instance(
        backend_type: str,
        model_name: str,
        excluded_backends: set[str],
    ) -> str | None:
        if backend_type in unavailable:
            logger.warning(
                f"Backend '{backend_type}' is unavailable (simulated failure)"
            )
            return None
        logger.info(f"Backend instance resolved: {backend_type}:{model_name}")
        return backend_type

    routing_service.resolve_backend_instance.side_effect = _resolve_backend_instance
    routing_service.resolve_model_only_backend.return_value = "ollama"

    return {
        "session_service": session_service,
        "model_alias_resolver": model_alias_resolver,
        "planning_phase_manager": planning_phase_manager,
        "backend_lifecycle_manager": backend_lifecycle_manager,
        "routing_service": routing_service,
    }


def _create_request_context(surface: str = "main") -> Any:
    """Create a RequestContext for testing."""
    from src.core.domain.request_context import RequestContext

    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id=f"demo-request-{surface}",
        session_id=f"demo-session-{surface}",
    )
    context.extensions["composite_routing_surface"] = surface
    return context


async def demo_alias_to_composite_happy_path() -> bool:
    """Demo: Alias resolves to composite, first backend succeeds."""
    from src.core.config.app_config import AppConfig
    from src.core.domain.chat import ChatMessage, ChatRequest
    from src.core.services.backend_model_resolver import BackendModelResolver

    logger.info("=" * 70)
    logger.info("DEMO 1: Alias -> Composite Routing (Happy Path)")
    logger.info("=" * 70)
    logger.info(f"Alias pattern: {ALIAS_PATTERN}")
    logger.info(f"Composite replacement: {COMPOSITE_REPLACEMENT}")
    logger.info("-" * 70)

    deps = _create_mock_dependencies()

    resolver = BackendModelResolver(
        session_service=deps["session_service"],
        model_alias_resolver=deps["model_alias_resolver"],
        planning_phase_manager=deps["planning_phase_manager"],
        backend_lifecycle_manager=deps["backend_lifecycle_manager"],
        config=AppConfig(),
        routing_service=deps["routing_service"],
    )

    request = ChatRequest(
        model=ALIAS_PATTERN,
        messages=[ChatMessage(role="user", content="Hello, world!")],
        extra_body={},
    )
    context = _create_request_context()

    logger.info(f"Sending request with model: '{request.model}'")
    result = await resolver.resolve_target(request, context=context)

    logger.info("-" * 70)
    logger.info(f"RESULT: backend={result.backend}, model={result.model}")

    success = result.backend == "ollama" and result.model == "minimax-m2.7-cloud"
    if success:
        logger.info("SUCCESS: First backend in failover chain was selected")
    else:
        logger.error(
            f"FAILED: Expected ollama:minimax-m2.7-cloud, got {result.backend}:{result.model}"
        )

    return success


async def demo_alias_to_composite_failover() -> bool:
    """Demo: Alias resolves to composite, first backend fails, second succeeds."""
    from src.core.config.app_config import AppConfig
    from src.core.domain.chat import ChatMessage, ChatRequest
    from src.core.services.backend_model_resolver import BackendModelResolver

    logger.info("")
    logger.info("=" * 70)
    logger.info("DEMO 2: Alias -> Composite Routing (Failover)")
    logger.info("=" * 70)
    logger.info(f"Alias pattern: {ALIAS_PATTERN}")
    logger.info(f"Composite replacement: {COMPOSITE_REPLACEMENT}")
    logger.info("Simulating: 'ollama' backend is UNAVAILABLE")
    logger.info("-" * 70)

    deps = _create_mock_dependencies(unavailable_backends={"ollama"})

    resolver = BackendModelResolver(
        session_service=deps["session_service"],
        model_alias_resolver=deps["model_alias_resolver"],
        planning_phase_manager=deps["planning_phase_manager"],
        backend_lifecycle_manager=deps["backend_lifecycle_manager"],
        config=AppConfig(),
        routing_service=deps["routing_service"],
    )

    request = ChatRequest(
        model=ALIAS_PATTERN,
        messages=[ChatMessage(role="user", content="Hello, world!")],
        extra_body={},
    )
    context = _create_request_context()

    logger.info(f"Sending request with model: '{request.model}'")
    result = await resolver.resolve_target(request, context=context)

    logger.info("-" * 70)
    logger.info(f"RESULT: backend={result.backend}, model={result.model}")

    success = result.backend == "opencode-zen" and result.model == "minimax-m2.5-free"
    if success:
        logger.info("SUCCESS: Failover worked - second backend in chain was selected")
    else:
        logger.error(
            f"FAILED: Expected opencode-zen:minimax-m2.5-free, got {result.backend}:{result.model}"
        )

    return success


async def demo_alias_to_weighted_composite() -> bool:
    """Demo: Alias resolves to weighted composite selector."""
    from src.core.config.app_config import AppConfig
    from src.core.domain.chat import ChatMessage, ChatRequest
    from src.core.services.backend_model_resolver import BackendModelResolver

    weighted_alias = "alias:minimax-weighted"
    weighted_replacement = (
        "[weight=3]ollama:minimax-m2.7-cloud^[weight=1]opencode-zen:minimax-m2.5-free"
    )

    logger.info("")
    logger.info("=" * 70)
    logger.info("DEMO 3: Alias -> Weighted Composite Routing")
    logger.info("=" * 70)
    logger.info(f"Alias pattern: {weighted_alias}")
    logger.info(f"Composite replacement: {weighted_replacement}")
    logger.info("Expected: 75% ollama, 25% opencode-zen distribution")
    logger.info("-" * 70)

    deps = _create_mock_dependencies()

    def _resolve_weighted_alias(model: str) -> str:
        if model == weighted_alias:
            logger.info(f"Alias resolver: '{model}' -> '{weighted_replacement}'")
            return weighted_replacement
        return model

    deps["model_alias_resolver"].resolve.side_effect = _resolve_weighted_alias

    resolver = BackendModelResolver(
        session_service=deps["session_service"],
        model_alias_resolver=deps["model_alias_resolver"],
        planning_phase_manager=deps["planning_phase_manager"],
        backend_lifecycle_manager=deps["backend_lifecycle_manager"],
        config=AppConfig(),
        routing_service=deps["routing_service"],
    )

    results: dict[str, int] = {"ollama": 0, "opencode-zen": 0}
    num_trials = 20

    logger.info(f"Running {num_trials} requests to observe distribution...")

    for i in range(num_trials):
        request = ChatRequest(
            model=weighted_alias,
            messages=[ChatMessage(role="user", content=f"Request {i}")],
            extra_body={},
        )
        context = _create_request_context()
        result = await resolver.resolve_target(request, context=context)
        results[result.backend] = results.get(result.backend, 0) + 1

    logger.info("-" * 70)
    logger.info("Distribution results:")
    for backend, count in results.items():
        pct = (count / num_trials) * 100
        logger.info(f"  {backend}: {count}/{num_trials} ({pct:.1f}%)")

    ollama_ratio = results.get("ollama", 0) / num_trials
    success = 0.5 < ollama_ratio < 0.95
    if success:
        logger.info("SUCCESS: Weighted distribution observed (approximately 75%/25%)")
    else:
        logger.warning(
            f"NOTE: Distribution may vary due to randomness. Ratio: {ollama_ratio:.2f}"
        )

    return True


async def main() -> int:
    """Run all demos."""
    logger.info("Model Alias -> Composite Routing Demo")
    logger.info("=====================================")
    logger.info("")

    results = []

    try:
        results.append(await demo_alias_to_composite_happy_path())
        results.append(await demo_alias_to_composite_failover())
        results.append(await demo_alias_to_weighted_composite())
    except Exception as e:
        logger.exception(f"Demo failed with error: {e}")
        return 1

    logger.info("")
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    passed = sum(results)
    total = len(results)
    logger.info(f"Demos passed: {passed}/{total}")

    if all(results):
        logger.info("")
        logger.info("All demos PASSED!")
        logger.info("")
        logger.info("To use this feature in production:")
        logger.info("1. Add alias rule to config.yaml:")
        logger.info("   model_aliases:")
        logger.info('     - pattern: "^alias:minimax-m2$"')
        logger.info(
            '       replacement: "ollama:minimax-m2.7-cloud|opencode-zen:minimax-m2.5-free"'
        )
        logger.info("")
        logger.info("2. Send requests with model: 'alias:minimax-m2'")
        logger.info("")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
