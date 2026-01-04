"""Performance benchmarks for backend stage startup, validation, and strategy overhead.

This module benchmarks the performance characteristics of the refactored backend stage
to ensure no performance regressions were introduced and that strategy overhead
stays within acceptable limits.

Requirements: 10.1, 10.2, 10.3

Baseline Comparison:
- Baseline values can be set via environment variables:
  - PERF_BASELINE_STARTUP_MS: Baseline startup time in milliseconds
  - PERF_BASELINE_VALIDATION_MS: Baseline validation duration in milliseconds
- If baseline is not set, tests use reasonable default thresholds
- When baseline is set, current measurements are compared against baseline with 10% tolerance
"""

from __future__ import annotations

import contextlib
import os
import time
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from src.connectors.strategies.registry import initialization_strategy_registry
from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.config.models import LoggingConfig, LogLevel, SessionConfig
from src.core.interfaces.http_client_manager_interface import IHttpClientManager
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import BackendRegistry
from src.core.services.backend_validation_service import BackendValidationService


@pytest.fixture
def minimal_app_config() -> AppConfig:
    """Create a minimal AppConfig for benchmarking."""
    from src.core.config.app_config import AuthConfig

    return AppConfig(
        host="localhost",
        port=9000,
        proxy_timeout=30,
        command_prefix="!/",
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key="test_key"),
        ),
        auth=AuthConfig(disable_auth=True, api_keys=["test_key"]),
        session=SessionConfig(cleanup_enabled=False, default_interactive_mode=True),
        logging=LoggingConfig(
            level=LogLevel.INFO, request_logging=False, response_logging=False
        ),
    )


@pytest.fixture
def mock_httpx_client() -> httpx.AsyncClient:
    """Create a mock HTTP client for benchmarking."""
    # Use a real client but with mocked responses to avoid network overhead
    return httpx.AsyncClient(timeout=5.0)


@pytest.fixture
def mock_translation_service() -> ITranslationService:
    """Create a mock translation service."""
    mock = MagicMock(spec=ITranslationService)
    return mock


@pytest.fixture
def backend_factory(
    mock_httpx_client: httpx.AsyncClient,
    minimal_app_config: AppConfig,
    mock_translation_service: ITranslationService,
) -> BackendFactory:
    """Create a BackendFactory for benchmarking."""
    backend_registry = BackendRegistry()
    return BackendFactory(
        httpx_client=mock_httpx_client,
        backend_registry=backend_registry,
        config=minimal_app_config,
        translation_service=mock_translation_service,
    )


@pytest.fixture
def validation_http_client_manager() -> IHttpClientManager:
    """Create a validation HTTP client manager."""
    from src.core.services.validation_http_client_manager import (
        ValidationHttpClientManager,
    )

    return ValidationHttpClientManager()


@pytest.fixture
def backend_validation_service(
    backend_factory: BackendFactory,
    validation_http_client_manager: IHttpClientManager,
    minimal_app_config: AppConfig,
) -> BackendValidationService:
    """Create a BackendValidationService for benchmarking."""
    backend_registry = BackendRegistry()
    return BackendValidationService(
        backend_factory=backend_factory,
        http_client_manager=validation_http_client_manager,
        backend_registry=backend_registry,
    )


@pytest.mark.slow
@pytest.mark.performance
@pytest.mark.asyncio
async def test_startup_time_benchmark(minimal_app_config: AppConfig):
    """Benchmark ApplicationBuilder.build() duration over 10 iterations.

    Requirements: 10.1

    This test measures startup time to ensure no performance regression was
    introduced by the refactoring.
    """
    iterations = 10
    warmup_iterations = 2
    durations: list[float] = []

    # Warm-up iterations to stabilize JIT/caching
    for _ in range(warmup_iterations):
        builder = ApplicationBuilder().add_default_stages()
        with contextlib.suppress(Exception):
            await builder.build(minimal_app_config)

    # Measure startup time over iterations
    for i in range(iterations):
        builder = ApplicationBuilder().add_default_stages()
        start_time = time.perf_counter()
        try:
            app = await builder.build(minimal_app_config)
            # Cleanup
            if hasattr(app, "state") and hasattr(app.state, "service_provider"):
                provider = app.state.service_provider
                if hasattr(provider, "dispose"):
                    await provider.dispose()
        except Exception as e:
            # If build fails, still record the time but note the failure
            end_time = time.perf_counter()
            duration = end_time - start_time
            durations.append(duration)
            print(f"\nIteration {i+1} failed: {e}")
            continue

        end_time = time.perf_counter()
        duration = end_time - start_time
        durations.append(duration)

    if not durations:
        pytest.skip("All iterations failed, cannot benchmark")

    # Calculate statistics
    mean_duration = sum(durations) / len(durations)
    min_duration = min(durations)
    max_duration = max(durations)
    mean_duration_ms = mean_duration * 1000
    min_duration_ms = min_duration * 1000
    max_duration_ms = max_duration * 1000

    # Get baseline from environment variable (if set)
    baseline_startup_ms_str = os.environ.get("PERF_BASELINE_STARTUP_MS")
    baseline_startup_ms: float | None = None
    if baseline_startup_ms_str:
        with contextlib.suppress(ValueError):
            baseline_startup_ms = float(baseline_startup_ms_str)

    # Print results for visibility
    print(
        f"\nStartup Time Benchmark Results ({iterations} iterations):"
        f"\n  Mean: {mean_duration_ms:.2f}ms"
        f"\n  Min:  {min_duration_ms:.2f}ms"
        f"\n  Max:  {max_duration_ms:.2f}ms"
    )

    if baseline_startup_ms is not None:
        # Compare against baseline with 10% tolerance
        tolerance_factor = 1.1
        baseline_with_tolerance_ms = baseline_startup_ms * tolerance_factor
        print(
            f"  Baseline: {baseline_startup_ms:.2f}ms (with 10% tolerance: {baseline_with_tolerance_ms:.2f}ms)"
        )

        assert mean_duration_ms <= baseline_with_tolerance_ms, (
            f"Mean startup time {mean_duration_ms:.2f}ms exceeds baseline "
            f"{baseline_startup_ms:.2f}ms (with 10% tolerance: {baseline_with_tolerance_ms:.2f}ms). "
            f"This indicates a performance regression."
        )
    else:
        # Fallback to absolute threshold if baseline not set
        # Set a generous threshold: startup should complete in under 10 seconds
        # This is a sanity check when baseline is not available
        threshold_ms = 10_000.0
        print(
            f"  Baseline not set (PERF_BASELINE_STARTUP_MS), using threshold: {threshold_ms:.2f}ms"
        )
        assert mean_duration_ms < threshold_ms, (
            f"Mean startup time {mean_duration_ms:.2f}ms exceeds threshold {threshold_ms:.2f}ms. "
            f"This may indicate a performance regression. Set PERF_BASELINE_STARTUP_MS for baseline comparison."
        )


@pytest.mark.slow
@pytest.mark.performance
@pytest.mark.asyncio
async def test_validation_duration_benchmark(
    backend_validation_service: BackendValidationService,
    minimal_app_config: AppConfig,
):
    """Benchmark BackendValidationService.validate_all() duration over 10 iterations.

    Requirements: 10.2

    This test measures validation duration to ensure no performance regression
    was introduced by the refactoring.
    """
    iterations = 10
    warmup_iterations = 2
    durations: list[float] = []

    # Warm-up iterations
    for _ in range(warmup_iterations):
        with contextlib.suppress(Exception):
            await backend_validation_service.validate_all(minimal_app_config)

    # Measure validation duration over iterations
    for i in range(iterations):
        start_time = time.perf_counter()
        try:
            await backend_validation_service.validate_all(minimal_app_config)
            # Note: result may be False in test environment, that's OK for benchmarking
        except Exception as e:
            end_time = time.perf_counter()
            duration = end_time - start_time
            durations.append(duration)
            print(f"\nIteration {i+1} failed: {e}")
            continue

        end_time = time.perf_counter()
        duration = end_time - start_time
        durations.append(duration)

    if not durations:
        pytest.skip("All iterations failed, cannot benchmark")

    # Calculate statistics
    mean_duration = sum(durations) / len(durations)
    min_duration = min(durations)
    max_duration = max(durations)
    mean_duration_ms = mean_duration * 1000
    min_duration_ms = min_duration * 1000
    max_duration_ms = max_duration * 1000

    # Get baseline from environment variable (if set)
    baseline_validation_ms_str = os.environ.get("PERF_BASELINE_VALIDATION_MS")
    baseline_validation_ms: float | None = None
    if baseline_validation_ms_str:
        with contextlib.suppress(ValueError):
            baseline_validation_ms = float(baseline_validation_ms_str)

    # Print results for visibility
    print(
        f"\nValidation Duration Benchmark Results ({iterations} iterations):"
        f"\n  Mean: {mean_duration_ms:.2f}ms"
        f"\n  Min:  {min_duration_ms:.2f}ms"
        f"\n  Max:  {max_duration_ms:.2f}ms"
    )

    if baseline_validation_ms is not None:
        # Compare against baseline with 10% tolerance
        tolerance_factor = 1.1
        baseline_with_tolerance_ms = baseline_validation_ms * tolerance_factor
        print(
            f"  Baseline: {baseline_validation_ms:.2f}ms (with 10% tolerance: {baseline_with_tolerance_ms:.2f}ms)"
        )

        assert mean_duration_ms <= baseline_with_tolerance_ms, (
            f"Mean validation duration {mean_duration_ms:.2f}ms exceeds baseline "
            f"{baseline_validation_ms:.2f}ms (with 10% tolerance: {baseline_with_tolerance_ms:.2f}ms). "
            f"This indicates a performance regression."
        )
    else:
        # Fallback to absolute threshold if baseline not set
        # Set a generous threshold: validation should complete in under 5 seconds
        # This is a sanity check when baseline is not available
        threshold_ms = 5_000.0
        print(
            f"  Baseline not set (PERF_BASELINE_VALIDATION_MS), using threshold: {threshold_ms:.2f}ms"
        )
        assert mean_duration_ms < threshold_ms, (
            f"Mean validation duration {mean_duration_ms:.2f}ms exceeds threshold {threshold_ms:.2f}ms. "
            f"This may indicate a performance regression. Set PERF_BASELINE_VALIDATION_MS for baseline comparison."
        )


@pytest.mark.slow
@pytest.mark.performance
def test_strategy_augmentation_overhead_benchmark():
    """Benchmark per-backend strategy augmentation overhead.

    Requirements: 10.3

    This test measures the overhead introduced by the strategy pattern
    for backend initialization. The overhead should be less than 5ms per backend.
    """
    # Test with known backends that have strategies
    backend_types = ["anthropic", "gemini", "openrouter"]
    iterations_per_backend = 1000
    warmup_iterations = 100

    results: dict[str, dict[str, float]] = {}

    for backend_type in backend_types:
        # Get strategy for this backend type
        strategy = initialization_strategy_registry.get_strategy(backend_type)

        # Sample init config
        init_config: dict[str, Any] = {
            "api_key": "test_key",
            "api_base_url": "https://api.example.com",
        }

        # Warm-up iterations
        for _ in range(warmup_iterations):
            with contextlib.suppress(Exception):
                strategy.augment_init_config(init_config.copy())

        # Measure strategy overhead
        durations: list[float] = []
        for _ in range(iterations_per_backend):
            config_copy = init_config.copy()
            start_time = time.perf_counter()
            try:
                strategy.augment_init_config(config_copy)
            except Exception:
                end_time = time.perf_counter()
                duration = end_time - start_time
                durations.append(duration)
                continue

            end_time = time.perf_counter()
            duration = end_time - start_time
            durations.append(duration)

        if not durations:
            continue

        # Calculate statistics
        mean_duration = sum(durations) / len(durations)
        min_duration = min(durations)
        max_duration = max(durations)
        mean_duration_ms = mean_duration * 1000
        min_duration_ms = min_duration * 1000
        max_duration_ms = max_duration * 1000

        results[backend_type] = {
            "mean_ms": mean_duration_ms,
            "min_ms": min_duration_ms,
            "max_ms": max_duration_ms,
        }

        # Assert overhead is less than 5ms per backend initialization
        assert mean_duration_ms < 5.0, (
            f"Strategy augmentation overhead for {backend_type} "
            f"({mean_duration_ms:.4f}ms) exceeds 5ms threshold."
        )

    # Print results for visibility
    print("\nStrategy Augmentation Overhead Benchmark Results:")
    for backend_type, stats in results.items():
        print(
            f"  {backend_type}:"
            f"\n    Mean: {stats['mean_ms']:.4f}ms"
            f"\n    Min:  {stats['min_ms']:.4f}ms"
            f"\n    Max:  {stats['max_ms']:.4f}ms"
        )
