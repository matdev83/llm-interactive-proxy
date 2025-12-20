# Requirements Document

## Introduction

This document specifies requirements for refactoring `src/core/ports/streaming_contracts.py` to remove “God Object” characteristics and re-establish a layered, modular architecture with clear cross-layer boundaries, while preserving existing runtime behavior and external contracts.

**Baseline (current code; from inspection)**:
- `src/core/ports/streaming_contracts.py` is 1,858 lines (`wc -l`)
- Total cyclomatic complexity: 396.0
- Max function cyclomatic complexity: 111
- Average function cyclomatic complexity: 8.43
- Number of functions: 47
- Maintainability index: 0.0

**Project Context**: Universal LLM Proxy - async FastAPI proxy with staged initialization, DI-managed services, adapter pattern for backend connectors, and a streaming pipeline used across multiple protocols/backends.

**Stakeholders**:
- Developers maintaining the streaming pipeline and streaming-dependent middleware/services
- Operators relying on stable streaming behavior, observability, and debuggability
- Clients consuming OpenAI/Anthropic/Gemini-compatible streaming endpoints

## Glossary

- **Streaming contracts**: shared interfaces and data structures used to represent streaming chunks and pipeline boundaries.
- **SSE**: Server-Sent Events format used for streaming responses.
- **StreamingContent**: unified streaming chunk representation used across the pipeline.
- **StopChunkWithUsage**: protective wrapper to prevent usage-bearing “stop chunk” leakage into plain content serialization.
- **Normalizer**: component converting provider-specific streaming formats into the canonical representation.
- **Processor**: streaming middleware component that transforms/enriches canonical chunks.
- **Assembler**: component that turns canonical chunks into an output wire format (for example SSE bytes).
- **God Object**: a module/class owning too many responsibilities, creating high coupling and low testability/maintainability.

## Requirements

### Requirement 1: God Object Mitigation and Decomposition Quality

**Objective:** As a developer, I want the responsibilities currently concentrated in `streaming_contracts.py` decomposed into cohesive components, so the streaming pipeline becomes maintainable and testable without merely relocating complexity.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1.1 When the refactoring is complete, the system shall reduce `src/core/ports/streaming_contracts.py` to < 600 lines (`wc -l`) by turning it into a small compatibility facade that re-exports public contracts.

1.2 When the refactoring introduces new modules or substantially expands existing ones to host extracted responsibilities, the system shall ensure every such single Python source file remains < 600 lines (`wc -l`).

1.3 When the refactoring is complete, the system shall ensure no single function or method in the refactored streaming-contracts surface area exceeds cyclomatic complexity 50 (radon CC, as reported by `scripts/analyze_complexity.py` or equivalent reporting).

1.4 When code is extracted from `src/core/ports/streaming_contracts.py`, the system shall not move any high-complexity function/method “as-is” into another module; instead, it shall decompose that logic into smaller cohesive units so that the complexity limits in 1.3 are met.

1.5 When the refactoring is complete, the system shall ensure no newly introduced module becomes a replacement “God Object” by exceeding a total cyclomatic complexity threshold of 200 (sum of function CC in the module, radon CC).

#### Technical Constraints

- The refactor shall preserve async correctness (no blocking I/O in async paths).
- The refactor shall follow SOLID and DRY principles, with responsibilities separated into focused collaborators.

### Requirement 2: Layered Architecture and Boundary Enforcement

**Objective:** As a developer, I want streaming contracts and shared abstractions to be isolated from transport/provider concerns, so cross-layer boundaries remain enforceable and dependency direction is stable.

**Priority:** P0 (Critical)

#### Acceptance Criteria

2.1 When the refactoring is complete, the system shall ensure streaming “ports/contracts” modules do not import transport/vendor libraries (for example `httpx`, FastAPI/Starlette types); any transport-specific exception mapping or IO-facing logic shall reside in an appropriate outer layer.

2.2 When provider-specific streaming formats need parsing/normalization, the system shall implement that parsing in provider-specific normalizers (or equivalent adapters) rather than embedding provider-specific parsing logic in shared contract types.

2.3 When the refactoring is complete, the system shall ensure the streaming contracts layer does not depend on backend connector modules (`src/connectors/`) to avoid inward dependency on adapters.

### Requirement 3: Public Contract and Backward Compatibility Preservation

**Objective:** As a developer, I want existing import sites and runtime behavior to remain stable, so the refactor does not force widespread rewrites or introduce streaming regressions.

**Priority:** P0 (Critical)

#### Acceptance Criteria

3.1 When the refactoring is complete, the system shall preserve the existing public import surface of `src.core.ports.streaming_contracts` for all currently used symbols (for example `StreamingContent`, `StopChunkWithUsage`, `UsageChunkLeakError`, `IStreamNormalizer`, `BaseStreamNormalizer`, `IStreamProcessor`, `IStreamAssembler`, `SentinelManager`, `StreamingErrorMapper`, `handle_streaming_error`).

3.2 When the refactoring is complete, the system shall preserve the runtime behavior of stop-chunk usage protection: When a stop chunk containing usage is present, the system shall prevent accidental stringification/implicit JSON serialization of that protected structure outside the approved serialization path.

3.3 When the refactoring is complete, the system shall preserve the streaming serialization semantics used by the proxy so that the client-observed SSE stream remains compatible with existing clients and test suites.

### Requirement 4: Streaming Semantics and Invariants Preservation

**Objective:** As a user and operator, I want streaming output semantics preserved, so the proxy continues to produce correct SSE streams and accurate usage data.

**Priority:** P1 (High)

#### Acceptance Criteria

4.1 When a chunk is usage-bearing stop content, the system shall serialize usage at the correct top-level location in the SSE payload (not as plain text content), and it shall emit the correct terminal done marker.

4.2 When the streaming pipeline receives whitespace-only text deltas, the system shall treat them as non-empty content and shall not drop them in ways that change client-visible text concatenation.

4.3 When tool calls are present in streaming content, the system shall preserve the existing behavior for sanitizing internal-only markers (for example removing internal fields and `extra_content`) before client emission.

4.4 When a chunk is a pure done marker, the system shall preserve the existing behavior for detecting and emitting done markers without generating spurious content.

### Requirement 5: Dependency Injection and Test Seams

**Objective:** As a developer, I want extracted responsibilities to be testable and loosely coupled, so components can be unit tested and wired consistently through the DI container.

**Priority:** P1 (High)

#### Acceptance Criteria

5.1 When the refactoring introduces new stateful collaborators (for example mappers/serializers/formatters/validators used across the application), the system shall define interfaces in `src/core/interfaces/` and register implementations via the existing DI composition root.

5.2 When new collaborators are introduced, the system shall avoid implicit “fallback construction” inside application code (no “if dependency is None then create default” patterns) and shall prefer explicit DI wiring.

### Requirement 6: Verification, Regression Safety, and Documentation

**Objective:** As a maintainer, I want the refactor to be proven safe and easy to validate, so regressions can be detected early and the new boundaries are clear.

**Priority:** P0 (Critical)

#### Acceptance Criteria

6.1 When the refactoring is complete, the system shall pass the existing test suite relevant to streaming behavior (unit/integration/property/regression as applicable under the default pytest addopts).

6.2 When the refactoring is complete, the system shall include targeted characterization tests for any behavior that was previously only implicitly covered, especially around stop-chunk usage handling, SSE serialization, done marker handling, and error propagation.

6.3 When the refactoring is complete, the system shall document the new module boundaries and responsibilities in the design documentation for this spec so future contributors can keep complexity constrained.

## Out of Scope

- Adding new streaming features or changing existing streaming semantics
- Changing public HTTP API schemas, config precedence, or wire-capture formats
- Refactoring unrelated modules not required to decompose `streaming_contracts.py`

