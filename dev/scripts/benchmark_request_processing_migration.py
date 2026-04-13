#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import math
import statistics
import sys
import time
import tracemalloc
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    IBackendRequestPreparation,
)
from src.core.interfaces.quality_verifier_service_interface import (
    IQualityVerifierServiceFactory,
)
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.envelope_compatibility_adapter import (
    EnvelopeCompatibilityAdapter,
)
from src.core.services.migration_gate_service import MigrationGateService
from src.core.services.post_backend_response_coordinator import (
    PostBackendResponseCoordinator,
)
from src.core.services.quality_verifier_service import QualityVerifierService

WARMUP_ITERATIONS = 100
TIMED_ITERATIONS = 1000
BASELINE_DENOMINATOR_FLOOR = 0.001
BENCHMARK_BACKEND_NAME = "benchmark-backend"


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    enable_core_canonical_path: bool
    connector_stream_first: bool
    backend_mode: str


@dataclass(frozen=True)
class ScenarioMeasurement:
    timings_ns: list[int]
    p50_ms: float
    p95_ms: float
    mean_ms: float
    peak_memory_bytes: int


@dataclass(frozen=True)
class ScenarioPair:
    name: str
    candidate: ScenarioConfig
    baseline: ScenarioConfig


class _NoopRequestPreparation(IBackendRequestPreparation):
    async def prepare(
        self, request: ChatRequest, command_result: Any
    ) -> ChatRequest | None:
        del command_result
        return request


class _NoopStreamingHandler:
    async def handle(
        self,
        stream: StreamingResponseEnvelope,
        request: ChatRequest,
        context: RequestContext,
        processing_context: Any,
    ) -> StreamingResponseEnvelope:
        del request, context, processing_context
        return stream


class _BenchmarkBackendProcessor(IBackendProcessor):
    def __init__(self, mode: str) -> None:
        self._mode = mode

    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        del request, session_id, context
        if self._mode == "blocking":
            return ResponseEnvelope(
                content={
                    "id": "bench-non-stream",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "fixed"},
                            "finish_reason": "stop",
                        }
                    ],
                },
                status_code=200,
            )

        async def _stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "fixed"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {}, "finish_reason": "stop"}]}
            )

        return StreamingResponseEnvelope(content=_stream(), status_code=200)


class _NoopResponseProcessor(IResponseProcessor):
    async def process_response(
        self,
        response: Any,
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResponse:
        del session_id, context
        return ProcessedResponse(content=response)

    def process_streaming_response(
        self,
        response_iterator: AsyncIterator[Any],
        session_id: str,
        context: RequestContext | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        del session_id, context

        async def _wrapped() -> AsyncIterator[ProcessedResponse]:
            async for item in response_iterator:
                if isinstance(item, ProcessedResponse):
                    yield item
                else:
                    yield ProcessedResponse(content=item)

        return _wrapped()

    async def register_middleware(
        self, middleware: IResponseMiddleware, priority: int = 0
    ) -> None:
        del middleware, priority


class _NoopQualityVerifierFactory(IQualityVerifierServiceFactory):
    def create(
        self,
        model_spec: str,
        max_history: int | None = None,
        max_consecutive_failures: int = 5,
        cooldown_seconds: int = 300,
        notification_service: Any | None = None,
    ) -> QualityVerifierService:
        del (
            model_spec,
            max_history,
            max_consecutive_failures,
            cooldown_seconds,
            notification_service,
        )
        return cast(QualityVerifierService, object())


def calculate_p95(values: list[int] | list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(float(value) for value in values)
    rank = max(1, math.ceil(0.95 * len(sorted_values)))
    return sorted_values[rank - 1]


def calculate_p50(values: list[int] | list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(float(value) for value in values))


def compute_percent_delta(candidate: float, baseline: float) -> float:
    denominator = max(float(baseline), BASELINE_DENOMINATOR_FLOOR)
    return ((float(candidate) - float(baseline)) / denominator) * 100.0


def select_worst_case_scenario(values: dict[str, float]) -> tuple[str, float]:
    if not values:
        return ("", 0.0)
    return max(values.items(), key=lambda item: item[1])


def _build_request() -> ChatRequest:
    return ChatRequest(
        model="benchmark-model",
        messages=[ChatMessage(role="user", content="ping")],
        stream=False,
    )


def _build_context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        backend=BENCHMARK_BACKEND_NAME,
        effective_model="benchmark-model",
    )


def _build_manager(scenario: ScenarioConfig) -> BackendRequestManager:
    post_backend_response_coordinator = PostBackendResponseCoordinator(
        streaming_handler=_NoopStreamingHandler()
    )
    return BackendRequestManager(
        backend_processor=_BenchmarkBackendProcessor(mode=scenario.backend_mode),
        response_processor=_NoopResponseProcessor(),
        quality_verifier_service_factory=_NoopQualityVerifierFactory(),
        request_preparation=_NoopRequestPreparation(),
        post_backend_response_coordinator=post_backend_response_coordinator,
        migration_gate_service=MigrationGateService.from_flags(
            enable_core_canonical_path=scenario.enable_core_canonical_path,
            emit_path_selection_metadata=False,
            connector_stream_first={
                BENCHMARK_BACKEND_NAME: scenario.connector_stream_first
            },
        ),
        envelope_compatibility_adapter=EnvelopeCompatibilityAdapter(),
    )


async def _run_measurement(scenario: ScenarioConfig) -> ScenarioMeasurement:
    manager = _build_manager(scenario)
    request = _build_request()
    context = _build_context()
    session_id = "benchmark-session"

    tracemalloc.start()
    try:
        for _ in range(WARMUP_ITERATIONS):
            await manager.process_backend_request(request, session_id, context)

        timings_ns: list[int] = []
        for _ in range(TIMED_ITERATIONS):
            start_ns = time.perf_counter_ns()
            await manager.process_backend_request(request, session_id, context)
            timings_ns.append(time.perf_counter_ns() - start_ns)

        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    p50_ns = calculate_p50(timings_ns)
    p95_ns = calculate_p95(timings_ns)
    mean_ns = statistics.fmean(float(value) for value in timings_ns)
    return ScenarioMeasurement(
        timings_ns=timings_ns,
        p50_ms=p50_ns / 1_000_000.0,
        p95_ms=p95_ns / 1_000_000.0,
        mean_ms=mean_ns / 1_000_000.0,
        peak_memory_bytes=int(peak_bytes),
    )


def _measurement_to_dict(measurement: ScenarioMeasurement) -> dict[str, Any]:
    return {
        "timings_ns": measurement.timings_ns,
        "p50_ms": measurement.p50_ms,
        "p95_ms": measurement.p95_ms,
        "mean_ms": measurement.mean_ms,
        "peak_memory_bytes": measurement.peak_memory_bytes,
    }


async def run_benchmark() -> dict[str, Any]:
    scenario_groups = [
        ScenarioPair(
            name="canonical_non_stream_blocking",
            candidate=ScenarioConfig(
                name="canonical_non_stream_blocking",
                enable_core_canonical_path=True,
                connector_stream_first=False,
                backend_mode="blocking",
            ),
            baseline=ScenarioConfig(
                name="canonical_non_stream_blocking_legacy_baseline",
                enable_core_canonical_path=False,
                connector_stream_first=False,
                backend_mode="blocking",
            ),
        ),
        ScenarioPair(
            name="connector_stream_first_non_stream",
            candidate=ScenarioConfig(
                name="connector_stream_first_non_stream",
                enable_core_canonical_path=True,
                connector_stream_first=True,
                backend_mode="streaming",
            ),
            baseline=ScenarioConfig(
                name="connector_stream_first_non_stream_legacy_baseline",
                enable_core_canonical_path=False,
                connector_stream_first=True,
                backend_mode="streaming",
            ),
        ),
    ]

    results: dict[str, Any] = {}
    p95_deltas: dict[str, float] = {}
    memory_deltas: dict[str, float] = {}

    for index, group in enumerate(scenario_groups):
        if index > 0:
            gc.collect()

        candidate = await _run_measurement(group.candidate)
        baseline = await _run_measurement(group.baseline)

        p95_delta = compute_percent_delta(candidate.p95_ms, baseline.p95_ms)
        memory_delta = compute_percent_delta(
            float(candidate.peak_memory_bytes), float(baseline.peak_memory_bytes)
        )
        p95_deltas[group.name] = p95_delta
        memory_deltas[group.name] = memory_delta

        results[group.name] = {
            "candidate": _measurement_to_dict(candidate),
            "baseline": _measurement_to_dict(baseline),
            "non_stream_p95_latency_delta_pct": p95_delta,
            "memory_delta_pct": memory_delta,
        }

    worst_p95_name, worst_p95_delta = select_worst_case_scenario(p95_deltas)
    worst_memory_name, worst_memory_delta = select_worst_case_scenario(memory_deltas)

    return {
        "config": {
            "warmup_iterations": WARMUP_ITERATIONS,
            "timed_iterations": TIMED_ITERATIONS,
            "baseline_denominator_floor": BASELINE_DENOMINATOR_FLOOR,
        },
        "scenarios": results,
        "worst_case": {
            "non_stream_p95_latency_delta_pct": {
                "scenario": worst_p95_name,
                "value": worst_p95_delta,
            },
            "memory_delta_pct": {
                "scenario": worst_memory_name,
                "value": worst_memory_delta,
            },
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark request-processing migration non-stream scenarios."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write JSON benchmark output.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    payload = asyncio.run(run_benchmark())

    output_json = json.dumps(payload, indent=2)
    print(output_json)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_json + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
