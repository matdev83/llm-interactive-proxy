# Requirements Document

## Introduction

This specification defines requirements for introducing strict, explicit typed data contracts for cross-layer and cross-domain data exchange in the Universal LLM Proxy. The goal is to reduce reliance on ad hoc `dict`/`Any` types in core boundaries, simplify data flow through the request and backend completion pipelines, and improve debuggability while preserving all externally observable behavior.

### Project Description (Input)

````
Effort: strict typing for cross-layer, cross-domain data types ``` Problem statement: this project endorses strict typing, modular, layered architecture with loose component coupling and strong cross-layer separation of concerns. The problem I noticed is that a lot of return types/input param types rely on ad hoc complex types like dicts, unions or Any. I think that, especially for cross-layer or cross-domain data passing we should enforce more strictier typing for complex types. I was thinking of Pydantic v2 models or dataclasses, since they are used widely across the codebase (but not yet everywhere). I think that modularity of the code and ease of the debugging should be greatly increased if we avoid cross-domain use of ad hoc types. Correct me if Im plain wrong here!
  But if you think so well proceed. One more problem: I also noticed that data flow (not the control flow, but the flow of actual pieces of data inside the proxy) is rather complicated, with a lot of wrapping, unwrapping, casts, converts, copying and so on. I think we should address this issue also by introduction of some strongly typed and preferabely immutable types which should get preserved (without conversions back and forth) during the whole passage of data fragments through this proxy. Some smart OOP design patterns should be used to apply mutations in an additive form (like Copy On Write, decoration or anything else comes up into your mind). We also
````

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining and extending the request processing and backend execution pipelines
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications
- Connector authors implementing provider adapters

## Requirements

### 1. Compatibility and External Behavior Preservation
**Objective:** As a developer, I want typed contract adoption to preserve the proxy’s current externally observable behavior, so that existing clients, controllers, connectors, and tests continue to work unchanged.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1 The LLM Proxy shall preserve existing HTTP API request and response shapes for all supported frontend protocols (OpenAI-compatible, Anthropic-compatible, Gemini-compatible).
1.2 When an existing client request is accepted by the proxy today, the LLM Proxy shall accept it and produce a semantically equivalent response after typed contracts are introduced.
1.3 The LLM Proxy shall preserve the existing error model (exception hierarchy and HTTP mapping) for client-visible errors.
1.4 When wire capture is enabled, the LLM Proxy shall continue to produce CBOR captures compatible with existing inspection and replay tooling.
1.5 When existing unit and integration tests are executed, the LLM Proxy shall pass without requiring modifications to tests whose intent is unrelated to this feature.

#### Technical Constraints
- Async compatibility: All I/O paths must remain `async/await` compatible.
- Layer separation: Typed contracts must not introduce transport framework types (FastAPI/Starlette) into connector-facing code.

### 2. Canonical Typed Data Contracts for Cross-Layer Exchange
**Objective:** As a developer, I want canonical, explicit contract types for cross-layer and cross-domain data exchange, so that core data shapes are stable, reusable, and understandable.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1 The LLM Proxy shall define a canonical typed contract for each cross-layer data exchange used by core request processing and backend completion flows.
2.2 The LLM Proxy shall define canonical contracts for, at minimum: inbound request payloads, request context, outbound backend requests, backend responses, streaming chunks, usage/metrics, and wire-capture records.
2.3 When a request enters through a controller endpoint, the controller layer shall convert the inbound payload into the canonical inbound request contract before invoking core processing services.
2.4 When the core processing pipeline performs backend execution, it shall represent outbound backend calls using the canonical backend request contract rather than ad hoc dict shapes.
2.5 When a connector returns a result, the LLM Proxy shall represent it using transport-agnostic response envelope contracts for downstream transport adapters.
2.6 Where multiple frontend protocols map to the same internal semantics, the LLM Proxy shall normalize them into shared canonical contracts rather than maintaining per-protocol ad hoc dict shapes across layers.

#### Technical Constraints
- DI compatibility: Contracts must be usable across services registered via the existing DI container patterns.
- Backends: Connector implementations must remain isolated from transport-layer request/response objects.

### 3. Typed Boundary Interfaces (Eliminate Ad Hoc Cross-Layer Types)
**Objective:** As a developer, I want cross-layer boundaries to be strictly typed, so that invalid or mismatched data shapes are caught early by tooling and tests.

**Priority:** P0 (Critical)

#### Acceptance Criteria
3.1 When a public interface exchanges contract-shaped data across layers (transport-to-core, core-to-core, core-to-connector), it shall use canonical contract types for inputs and outputs.
3.2 The LLM Proxy shall avoid using `Any` and unconstrained `dict[str, Any]` as the primary representation for contract-shaped data at cross-layer boundaries.
3.3 If an interface must carry an unstructured extension payload, the LLM Proxy shall constrain it to an explicitly documented extension field and a constrained type suitable for validation/serialization.
3.4 When static type checking is executed using the repository’s configured mypy settings, it shall succeed without introducing new `type: ignore` statements for cross-layer boundary code added or modified by this feature.

#### Technical Constraints
- Type-checking posture: Must remain compatible with the project’s mypy configuration (`disallow_untyped_defs = true`, not fully strict).

### 4. Boundary Conversion Points and Data Flow Simplification
**Objective:** As a developer, I want contract conversions to occur only at explicit boundary points, so that the internal pipeline avoids unnecessary wrapping/unwrapping, casting, and copying.

**Priority:** P1 (High)

#### Acceptance Criteria
4.1 The LLM Proxy shall define and document the boundary conversion points where data may change representation (transport ↔ canonical contracts, canonical contracts ↔ provider/connector payloads, canonical contracts ↔ persistence/capture representations).
4.2 When data flows between internal pipeline phases, the LLM Proxy shall preserve canonical contract types and shall not convert them back into raw dicts between phases.
4.3 When a conversion between representations is required, the LLM Proxy shall perform it once at the relevant boundary and shall not require repeated conversions for the same boundary within a single request lifecycle.
4.4 When a pipeline phase needs derived or auxiliary data, the LLM Proxy shall attach it as typed metadata/context rather than duplicating and reserializing the core contract payload.

#### Technical Constraints
- Debuggability: Boundary conversions must remain observable via logging and/or capture metadata without leaking secrets.

### 5. Immutability and Additive Mutation of Contracts
**Objective:** As a developer, I want contract objects to behave as immutable values, so that data flow is easier to reason about and debugging is improved.

**Priority:** P1 (High)

#### Acceptance Criteria
5.1 The LLM Proxy shall treat canonical cross-layer contracts as immutable values after construction.
5.2 When any component needs to modify a contract’s semantic fields (e.g., request redaction, tool filtering, parameter tuning), the LLM Proxy shall produce a new contract instance and preserve the original instance unchanged.
5.3 When modifications occur, the LLM Proxy shall retain provenance sufficient for debugging and accounting, including the reason for modification and the ability to access the original value.
5.4 While streaming responses are processed, the LLM Proxy shall avoid buffering entire streams solely for contract conversion or mutation.

#### Technical Constraints
- Accounting: Usage tracking and modification tracking must remain accurate when immutable contracts are versioned.

### 6. Validation and Error Handling for Contract Construction
**Objective:** As a developer, I want contract construction and validation to produce consistent, structured errors, so that failures are predictable and diagnosable.

**Priority:** P1 (High)

#### Acceptance Criteria
6.1 When a canonical contract is created from external input, the LLM Proxy shall validate it and shall surface validation failures as structured errors consistent with the existing error hierarchy.
6.2 If an internal contract invariant is violated, the LLM Proxy shall raise a structured internal error and include sufficient context for debugging without exposing sensitive content.
6.3 Where current behavior is explicitly fail-open (best-effort side effects), the LLM Proxy shall preserve fail-open semantics when introducing typed contracts.

#### Technical Constraints
- Error hierarchy: Exceptions must extend `LLMProxyError` where appropriate and remain compatible with existing FastAPI exception adapters.

### 7. Observability, Capture, and Replay Support
**Objective:** As an operator/developer, I want typed contracts to integrate with captures and replay, so that debugging and regression analysis becomes easier.

**Priority:** P2 (Medium)

#### Acceptance Criteria
7.1 When wire capture is enabled, the LLM Proxy shall capture canonical contract representations (or their deterministic serialized form) for inbound requests, outbound backend requests, and backend responses.
7.2 The LLM Proxy shall ensure captured data can be round-tripped into canonical contracts to support simulation/replay workflows.
7.3 The LLM Proxy shall ensure contract serialization used for logging and capture is deterministic enough to support diff-based debugging.

#### Technical Constraints
- Wire capture encoding: CBOR capture remains the primary capture format and must remain supported.

### 8. Contributor Guidance and Enforcement
**Objective:** As a contributor, I want clear rules for where typed contracts must be used and where unstructured extensions are acceptable, so that new code does not regress toward ad hoc cross-layer types.

**Priority:** P2 (Medium)

#### Acceptance Criteria
8.1 The LLM Proxy shall provide developer documentation describing the canonical contract set and the allowed boundary conversion points.
8.2 The LLM Proxy shall provide explicit guidance on acceptable uses of unstructured extension fields and the process for promoting extensions into first-class contracts.

#### Technical Constraints
- Documentation must align with existing project architecture guidance (staged init, DI, domain/transport separation).

## Non-Functional Requirements

### NFR 1: Performance
1. When processing non-streaming requests, the LLM Proxy shall avoid introducing deep-copy behavior for large request/response payloads in the common path.
2. While processing streaming responses, the LLM Proxy shall not introduce buffering that materially increases time-to-first-byte relative to baseline behavior.

### NFR 2: Reliability
1. The LLM Proxy shall preserve existing backend failover and retry behavior while introducing typed contracts.
2. If contract validation fails, the LLM Proxy shall fail deterministically with a structured error rather than producing partial or inconsistent downstream behavior.

### NFR 3: Observability
1. When contract validation fails, the LLM Proxy shall emit structured logs with correlation identifiers (e.g., request ID/session ID where available) to support troubleshooting.
2. The LLM Proxy shall preserve the existing ability to inspect and replay captured traffic for debugging.

### NFR 4: Security
1. The LLM Proxy shall preserve existing redaction and secret-handling behavior when introducing typed contracts.
2. When logging contract data for errors or debugging, the LLM Proxy shall avoid emitting sensitive request/response content unless existing capture/debug configuration explicitly permits it.

## Glossary
| Term | Definition |
|------|------------|
| Canonical contract | A single, named typed representation used consistently across layer boundaries for a specific kind of data (request, response, usage, capture, etc.). |
| Cross-layer | Data exchange between architectural layers (transport/controllers ↔ core services ↔ connectors/backends). |
| Cross-domain | Data exchange between separate subdomains/components (routing, failover, usage, capture, steering/safety, connectors). |
| Boundary conversion | A deliberate transformation between representations at a defined boundary (e.g., HTTP payload to contract, contract to provider request). |
| Immutability | Treating contract objects as values that are not mutated in-place after creation; changes result in new versions. |
| Extension field | A constrained, explicitly documented place for vendor/protocol-specific data that is not part of the canonical semantic contract. |
