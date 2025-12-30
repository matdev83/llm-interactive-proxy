# Requirements Document

## Introduction

This specification defines the requirements for hardening and completing the typed data contracts refactor (follow-up to `.kiro/specs/cross-layer-typed-data-contracts`). The goal is to reduce and control remaining cross-layer boundary leaks of `Any` / `dict[str, Any]` by converging on stable, canonical contracts for data exchange across Transport ↔ Core ↔ Connector seams, while preserving all externally observable behavior (HTTP APIs, streaming semantics, error mapping, and wire capture compatibility).

This effort is specifically concerned with *boundary surfaces* (interfaces and adapters) where cross-layer data is exchanged. Internal implementation details may remain flexible when they are not part of a boundary contract, but boundary signatures and boundary-carried payloads must use canonical contracts or JSON-serializable typed values.

**Discovered Constraints (from Gap Analysis + current code state)**:
- `dev/scripts/check_boundary_types.py` currently scans `src/core/interfaces/`, `src/core/domain/`, and `src/core/transport/` and reports ~638 violations; enforcement must be re-scoped to true boundary surfaces to become actionable.
- The connector seam (`src/connectors/`) is a cross-layer boundary but is not currently covered by the boundary type guardrail script; the enforcement scope must include at least the connector boundary API.
- Several canonical contracts already exist (`RequestContext`, `BackendTarget`, `UsageSummary`, `ResponseEnvelope`/`StreamingResponseEnvelope`, streaming `StreamingChunk`), but key boundary protocols (notably response-processing and transport adapter protocols) still expose `Any`/`dict[str, Any]`, limiting the practical benefits of the contract set.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining request/response processing and backend orchestration
- Connector authors implementing provider adapters
- Operators relying on captures, replay, and usage accounting for debugging
- End-users consuming LLM responses through client applications

## Requirements

### Requirement 1: Compatibility and External Behavior Preservation
**Objective:** As a developer/operator, I want boundary hardening to preserve current client-visible behavior, so that existing clients, connectors, and tests continue to work.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1 The LLM Proxy shall preserve existing HTTP API request and response shapes for all supported frontend protocols (OpenAI Chat Completions, OpenAI Responses API, Anthropic Messages, Gemini v1beta).
1.2 When a client request is accepted by the current proxy version, the LLM Proxy shall accept the same request after boundary hardening and produce a semantically equivalent response.
1.3 If a client request fails today with a client-visible error, then the LLM Proxy shall fail with the same error classification and HTTP mapping after boundary hardening.
1.4 While wire capture is enabled, the LLM Proxy shall continue to produce CBOR captures compatible with existing inspection and replay tooling.
1.5 When existing unit and integration tests are executed, the LLM Proxy shall pass them without requiring modifications to tests whose intent is unrelated to this feature.

#### Technical Constraints
- Async compatibility: Cross-layer changes must remain `async/await` compatible.
- Layer separation: Boundary types must not introduce FastAPI/Starlette types into connector-facing code.
- Error hierarchy: Client-visible errors must remain compatible with the `LLMProxyError` mapping used by FastAPI exception adapters.

### Requirement 2: Canonical Typed Contracts at Cross-Layer Boundaries
**Objective:** As a developer, I want cross-layer seams to exchange canonical, explicit contracts instead of ad hoc dicts, so that data flow is stable, reusable, and debuggable.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1 When an HTTP request is adapted by the transport/controller layer, the LLM Proxy shall construct a canonical request context contract and attach the canonical inbound request contract before invoking core request processing.
2.2 When core request processing hands off execution to backend orchestration, the LLM Proxy shall represent routing outputs (backend selection, effective model, and URI parameters) using canonical typed contracts rather than ad hoc dict shapes.
2.3 When core orchestration invokes a connector backend, the LLM Proxy shall pass canonical request and context contracts without converting them into `dict[str, Any]` payloads.
2.4 When a connector returns a non-streaming result, the LLM Proxy shall represent it using a transport-agnostic response envelope contract with typed usage and JSON-serializable metadata.
2.5 While processing streaming responses, when a streaming chunk crosses a boundary between core response processing and transport serialization, the LLM Proxy shall represent it using a typed contract (e.g., `ProcessedResponse` and/or `StreamingChunk`) rather than raw `Any`.
2.6 Where protocol- or vendor-specific data must cross a boundary, the LLM Proxy shall carry it only via an explicitly documented extension mechanism (an “approved extension container/field”) and shall not introduce new ad hoc cross-layer extension fields.
2.7 Where backward compatibility requires a boundary contract field to remain permissive, the LLM Proxy shall document the exception, constrain it to the smallest practical surface, and provide a clear promotion path to a typed field or typed extension container.

#### Technical Constraints
- JSON safety: Boundary extension payload values must be JSON-serializable (e.g., `JsonValue`) to support deterministic logging/capture.
- Single representation: For any given concept (request, target, usage, response), boundary code must not introduce multiple parallel representations without an explicit conversion point.

### Requirement 3: Boundary Type Guardrails and Enforcement
**Objective:** As a contributor, I want automated checks that prevent regressions toward `Any`/ad hoc dicts at boundaries, so that typed contract hardening remains durable over time.

**Priority:** P0 (Critical)

#### Acceptance Criteria
3.1 The project shall define and document the “boundary surface enforcement scope” as an explicit list of directories and/or modules.
3.2 The boundary surface enforcement scope shall include the connector layer (`src/connectors/`) in addition to transport and core boundary surfaces.
3.3 When `./.venv/Scripts/python.exe dev/scripts/check_boundary_types.py` (or an equivalent documented boundary type check) is executed for the declared boundary surface enforcement scope, the command shall exit with code 0 for a compliant codebase.
3.4 If the boundary type check detects a violation, then it shall report a file path, line/column, and a human-readable message describing the violation.
3.5 Where a boundary exception is required (an allowed use of `Any` or `dict[str, Any]`), the project shall document the exception and limit it to an explicitly allowlisted scope with rationale.
3.6 The project shall provide developer documentation describing boundary contract rules, the boundary type check command, and the expected remediation workflow for violations.
3.7 When a change introduces a new non-allowlisted boundary type violation, the project’s required verification workflow shall fail.

#### Technical Constraints
- Guardrails must remain practical: the check must be fast enough for developer workflows and must not block legitimate internal-only uses of dynamic data.

### Requirement 4: Connector-Facing Contract Hardening
**Objective:** As a connector author, I want stable, typed connector-facing contracts, so that connectors can be implemented and maintained with predictable inputs/outputs and mypy support.

**Priority:** P1 (High)

#### Acceptance Criteria
4.1 The LLM Proxy shall invoke connector backends using the canonical request contract and shall not pass `dict[str, Any]` payloads from core orchestration into connectors; any legacy compatibility for dict-shaped inputs must be confined behind an explicitly named connector boundary adapter (see 4.4).
4.2 When a connector is invoked, the LLM Proxy shall provide “processed messages” using a typed representation consistent with the canonical request message contract (e.g., `Sequence[ChatMessage]`) rather than an untyped list.
4.3 If connector invocation requires provider-specific options, then the LLM Proxy shall constrain connector-bound option values to JSON-serializable typed values (or provide a dedicated typed options contract) and keep non-JSON runtime objects out of connector options/kwargs.
4.4 Where backward compatibility is required for existing connectors or tests, the LLM Proxy shall provide compatibility adapters that convert legacy shapes at the connector boundary without leaking legacy shapes into core services.

#### Technical Constraints
- Connector contracts must remain transport-agnostic and must not depend on FastAPI/Starlette types.
- Connector cancellation must use a stable typed interface (e.g., `ISessionCancellationCoordinator | None`) rather than `Any` once it crosses the core → connector seam.

### Requirement 5: Centralized Legacy Compatibility and Explicit Conversion Points
**Objective:** As a developer, I want legacy compatibility logic to be centralized at explicit conversion points, so that core services operate on stable typed inputs and avoid hidden conversion churn.

**Priority:** P1 (High)

#### Acceptance Criteria
5.1 When a core service interface accepts a canonical contract type for a concept (request, context, target, usage, response), the interface shall not also accept an untyped dict representation of the same concept except via an explicitly named compatibility wrapper.
5.2 When a legacy dict shape is provided at a boundary conversion point, the LLM Proxy shall either convert it into the canonical contract or reject it with a structured error consistent with the existing error hierarchy.
5.3 While executing a request through the core pipeline, the LLM Proxy shall preserve a single canonical representation per concept and shall not repeatedly re-normalize the same data across multiple services.

#### Technical Constraints
- Fail-open vs fail-fast semantics must remain consistent with existing behavior for side effects and best-effort processing.

### Requirement 6: Typed Usage, Metadata, and Response Processing Boundaries
**Objective:** As a developer/operator, I want usage and metadata to be typed and JSON-safe at boundary seams, so that response adaptation, capture, and debugging are deterministic and robust.

**Priority:** P1 (High)

#### Acceptance Criteria
6.1 When usage information crosses a boundary between connectors, core services, and transport adapters, the LLM Proxy shall represent it using the canonical usage contract rather than `dict[str, Any]`.
6.2 When metadata is attached to responses at boundary seams, the LLM Proxy shall represent metadata as JSON-serializable typed values rather than unconstrained dicts.
6.3 While processing streaming responses, the LLM Proxy shall not require per-chunk conversion through ad hoc `dict[str, Any]` shapes to apply middleware, accumulate usage, or serialize output.

#### Technical Constraints
- Streaming path performance must remain sensitive to per-chunk overhead (no heavy per-chunk validation/conversion in hot paths unless strictly necessary).

### Requirement 7: Capture and Replay Alignment with Canonical Contracts
**Objective:** As an operator/developer, I want wire capture and replay to work with canonical contracts, so that debugging and regression analysis remain reliable and easier to automate.

**Priority:** P2 (Medium)

#### Acceptance Criteria
7.1 While wire capture is enabled, when capturing requests and responses, the LLM Proxy shall capture canonical contract representations (or their deterministic serialized form) while preserving raw bytes as the fidelity source of truth.
7.2 When captured traffic is decoded for simulation/replay, the decoder shall produce typed canonical contracts on a best-effort basis and shall return structured diagnostics for decode failures without raising exceptions.
7.3 The LLM Proxy shall ensure that serialization used for logging and capture is deterministic enough to support diff-based debugging and stable replay workflows.

#### Technical Constraints
- Wire capture encoding remains CBOR and must remain supported by existing tools.

### Requirement 8: Contributor Guidance for Typed Contract Boundaries
**Objective:** As a contributor, I want clear rules for canonical contracts and extensions, so that new code does not regress toward ad hoc cross-layer types.

**Priority:** P2 (Medium)

#### Acceptance Criteria
8.1 The project shall provide documentation describing the canonical contract set and the allowed boundary conversion points.
8.2 Where an extension container is used for cross-layer exchange, the project shall document the extension-field policy and the promotion process from extension keys into first-class typed fields.
8.3 The project shall document when `Any` is permitted (internal-only contexts) and when it is forbidden (boundary signatures and boundary-carried contract-shaped payloads).

#### Technical Constraints
- Documentation must align with staged initialization, DI patterns, and domain/transport separation practices described in project steering.

## Non-Functional Requirements

### NFR 1: Performance
NFR1.1 The LLM Proxy shall avoid introducing deep-copy behavior for large request/response payloads in the common path.
NFR1.2 While processing streaming responses, the LLM Proxy shall not introduce buffering that materially increases time-to-first-byte relative to baseline behavior.
NFR1.3 When typed contracts are updated during processing, the LLM Proxy shall preserve copy-on-write behavior rather than mutating canonical contracts in place.

### NFR 2: Reliability
NFR2.1 The LLM Proxy shall preserve existing backend failover and retry behavior while hardening boundary typing.
NFR2.2 If contract validation fails at a boundary conversion point, then the LLM Proxy shall fail deterministically with a structured error rather than producing partial downstream behavior.
NFR2.3 Where current behavior is explicitly fail-open for best-effort side effects, the LLM Proxy shall preserve fail-open semantics after boundary hardening.

### NFR 3: Observability
NFR3.1 When boundary conversion or validation fails, the LLM Proxy shall emit structured logs with correlation identifiers sufficient for troubleshooting.
NFR3.2 While wire capture is enabled, the LLM Proxy shall preserve the ability to inspect and replay captured traffic using existing tooling.

### NFR 4: Security
NFR4.1 The LLM Proxy shall preserve existing redaction and secret-handling behavior after boundary hardening.
NFR4.2 When logging contract data for errors or debugging, the LLM Proxy shall avoid emitting sensitive request/response content unless existing capture/debug configuration explicitly permits it.

## Glossary
| Term | Definition |
|------|------------|
| Boundary surface | A cross-layer seam where data is exchanged between Transport, Core services, and Connectors (including interface signatures and adapter I/O). |
| Boundary surface enforcement scope | The explicitly defined set of directories/modules covered by the boundary type guardrail check(s). |
| Canonical contract | A single, named typed representation used consistently across boundary surfaces for a specific concept (request, context, target, usage, response, capture). |
| Boundary type guardrail | An automated check that detects non-allowlisted `Any` / ad hoc dict usage in boundary signatures and contract-shaped payloads. |
| Extension container | A single explicitly named field used to carry vendor/protocol-specific data across boundaries using JSON-serializable typed values. |
| JSON-serializable typed value | A value constrained to JSON-safe types (e.g., `JsonValue`) suitable for deterministic logging/capture. |
