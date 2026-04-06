# Testing & TDD (Steering)

## Testing Philosophy

This project treats tests as behavior contracts, not just regression counters.

- **TDD default**: Red -> Green -> Refactor
- **Contract-first assertions**: validate observable behavior and protocol shape
- **Regression focus**: pin bugfixes and edge-case behavior explicitly
- **Deterministic by default**: prefer isolated, reproducible tests over flaky timing/network paths

## Executable-Specification Standard

Tests should be detailed enough that maintainers can recover intended behavior from
tests alone.

### What strong tests assert

- Inputs, outputs, and edge/error behavior (including shape/status semantics)
- Invariants and ordering constraints (especially for streaming and tool calls)
- Side effects where relevant (captures, persistence, usage/accounting, routing)
- Boundary correctness across DI seams, adapters, and controller/service handoffs

### What to avoid

- Re-encoding private implementation call graphs
- Brittle assertions tied to non-contract internals
- Over-mocking domain transformations that should be tested as real behavior

## Suite Topology and Execution Pattern

Primary test roots and patterns:

- `tests/unit/`: isolated service/domain/connector logic
- `tests/integration/`: composed runtime flows and endpoint behavior
- `tests/property/`: invariant-focused randomized checks
- `tests/regression/`, `tests/behavior/`, `tests/streaming_regression/`: targeted
  safety nets for known fragile areas

Pytest configuration and markers are centralized in `pyproject.toml`.

Default execution posture:

- Async mode enabled (`--asyncio-mode=auto`)
- Parallelized local runs (`-n 4 --dist=loadfile`)
- Timeout guards enabled by default

## Mocking and Boundary Guidance

- Mock external network boundaries (`httpx`, `respx`, `pytest-httpx`)
- Use fixtures for reusable setup and DI seam control (`conftest.py` layering)
- Keep true integration paths for protocol contract tests where composition matters
- When testing transforms/parsers, assert resulting domain/protocol shapes rather than
  only "called once" style checks

## High-Value Test Targets in This Codebase

- Frontend protocol compatibility (OpenAI/Anthropic/Gemini)
- Streaming and non-streaming behavior equivalence where expected
- Backend failover/retry/circuit-breaker behavior
- Session/user isolation guarantees
- Safety controls that must not destabilize the core routing path

## Canonical Commands

Use the in-repo interpreter:

```powershell
# Default suite (uses project addopts)
./.venv/Scripts/python.exe -m pytest

# Focused suites
./.venv/Scripts/python.exe -m pytest tests/unit
./.venv/Scripts/python.exe -m pytest tests/integration

# Marker-based runs
./.venv/Scripts/python.exe -m pytest -m "unit"
./.venv/Scripts/python.exe -m pytest -m "integration"
```

## Near-Term Testing Direction (Planning-Aligned)

Current planning priorities from `.planning/` emphasize:

- Better regression detection for core behavior, not just larger test count
- Faster feedback loops for iterative stabilization
- Stronger provider/protocol coverage in compatibility paths
- More explicit tests for core-vs-non-core isolation boundaries

---

_Updated: 2025-12-27_
_Reason: Clarify TDD default workflow and tests-as-specification standard_

_Updated: 2026-04-06_
_Reason: Sync with current pytest runtime posture and planning priorities for stabilization-focused test strategy_
