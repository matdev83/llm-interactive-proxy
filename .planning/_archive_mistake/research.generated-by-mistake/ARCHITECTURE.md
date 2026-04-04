# Architecture Patterns

**Domain:** Universal LLM proxy / agent control plane (brownfield evolution)
**Researched:** 2026-04-04

## Recommended Architecture

Use a **bounded orchestration core** with strict seams:

1. **Transport edge** (protocol-facing): OpenAI/Anthropic/Gemini-compatible controllers + transport adapters
2. **Canonical core** (policy-facing): request processing, safety/steering, routing, resilience, usage, capture
3. **Connector plane** (provider-facing): provider adapters implementing a narrow backend contract
4. **Control/ops plane** (operator-facing): health/reactivation, diagnostics, metrics, captures, auditing

In this repository, that maps to:
- Staged bootstrap and lifecycle: `src/core/app/stages/`
- Core orchestration/services: `src/core/services/`
- Canonical contracts and envelopes: `src/core/domain/` and `src/core/ports/`
- Backend connector implementations: `src/connectors/`
- DI boundaries and collaborator interfaces: `src/core/interfaces/`, `src/core/di/`

The design should continue to optimize for **one stable canonical request/response model plus many edge translators**, instead of many pairwise translators. That keeps protocol translation linear, not combinatorial, as connectors and frontends grow.

## Component Boundaries and Ownership Lines

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| Transport Controllers (`core/app/controllers`) | Parse protocol-specific HTTP requests, emit protocol-specific HTTP responses | Request Processor, FastAPI transport adapters |
| Transport Adapters (`core/transport/fastapi`) | Convert transport payloads <-> canonical contracts (`CanonicalChatRequest`, `ResponseEnvelope`) | Controllers, Core services |
| Request Processor (`core/services/request_processor_service.py`) | Orchestrate pre-backend pipeline (session enrich, command handling, transforms, backend handoff) | Internal phase components (`ISessionEnricher`, `ICommandHandler`, etc.), Backend completion flow |
| Safety/Steering Policy Services | Tool policies, dangerous-command protection, sandboxing, redaction, steering controls | Request Processor, command/tool middleware |
| Backend Completion Flow (`core/services/backend_completion_flow/service.py`) | Orchestrate backend invocation lifecycle: availability gating, session resolution, request prep, capture, usage, failover/recovery | Collaborators via `IBackend*` interfaces, connectors, resilience services |
| Connector Contract (`connectors/base.py::LLMBackend`) | Stable provider adapter API for backend calls and health/rate-limit signaling | Backend completion flow, provider SDK/API |
| Connector Implementations (`src/connectors/*`) | Provider-specific auth, request formatting, response parsing, stream behavior | Provider APIs only (through connector contract) |
| Control/Ops Services | Health checks, diagnostics, capture orchestration, usage accounting, stateful operations | Backend flow, controller diagnostics endpoints, storage |
| Persistence (`core/database`) | Durable state for sessions, usage, limits, auth/identity data | Core services |

**Ownership rule that prevents complexity collapse:**
- **Orchestrators own ordering only.**
- **Collaborators own behavior.**
- **Connectors own provider quirks only.**
- **Transport owns protocol quirks only.**

If a connector starts containing policy logic, or the orchestrator starts containing provider-specific branching, complexity debt accelerates.

## Data and Control Flow

## Control Flow (single request)

1. **Ingress**: controller receives OpenAI/Anthropic/Gemini request.
2. **Normalization**: transport adapter builds canonical request + `RequestContext`.
3. **Pre-backend orchestration** (`RequestProcessor`):
   - session enrichment
   - command flow/fast-path decision
   - best-effort side effects
   - backend request preparation and validation
   - outbound transform pipeline in fixed order (redaction -> first-message append -> edit precision -> tool filtering)
4. **Backend orchestration** (`BackendCompletionFlow`):
   - availability checks
   - backend/model target resolve
   - backend acquisition/invocation
   - failover/retry/recovery decisions
   - usage accounting wrapping
   - wire capture orchestration (outbound + inbound/stream)
5. **Egress**: response envelope translated to frontend protocol and returned.

## Data Flow (what crosses boundaries)

- **Transport -> Core:** `CanonicalChatRequest`, `RequestContext`
- **Core -> Connector:** canonical request + resolved backend target/model + typed kwargs
- **Connector -> Core:** `ResponseEnvelope` or `StreamingResponseEnvelope`
- **Core -> Transport:** envelope adapted to frontend protocol response
- **Core -> Ops:** canonical usage records, capture entries, health/routing events

This explicit contract flow is the right pattern for brownfield hardening because it localizes breakage and allows incremental refactors under typed seams.

## Patterns to Follow

### Pattern 1: Thin Orchestrator + Collaborator Mesh
**What:** Keep top-level orchestrators (`RequestProcessor`, `BackendCompletionFlow`) as sequencing engines, with capability extracted behind interfaces.
**When:** Any flow with >3 major decision branches (routing/safety/failover/usage).
**Example:** Existing split into `ISessionEnricher`, `IBackendPreparer`, `IBackendExecutor`, and `IBackendAvailabilityChecker`, `IFailureRecoveryExecutor`, etc.

### Pattern 2: Canonical Contract First
**What:** Convert protocol/provider payloads at boundaries; keep core logic canonical and transport-neutral.
**When:** Adding new frontend protocols, connector families, or stream formats.
**Example:** `CanonicalChatRequest` + `ResponseEnvelope` as internal source of truth.

### Pattern 3: Stage-Gated Startup
**What:** Preserve staged initialization order (infrastructure -> services -> steering -> backends -> health -> command -> processor -> controllers).
**When:** Adding new subsystem wiring, especially stateful/health-sensitive services.
**Example:** `DefaultApplicationStages` in `src/core/app/stages/application_stages.py`.

### Pattern 4: Plugin-Ready Connector Plane
**What:** Keep backend discovery and registration fail-open and contract-driven (entry points + compatibility constraints).
**When:** Expanding backend ecosystem and reducing core-merge burden.
**Example:** plugin API via `llm_proxy_backends` entry-point contract.

### Pattern 5: Evidence-First Operations
**What:** Treat wire capture and usage accounting as first-class, not debug add-ons.
**When:** Every backend integration, failover path, and streaming path.
**Example:** dedicated wire capture and usage orchestrators in backend completion flow collaborators.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Re-centralized God Orchestrator
**What:** New features added directly to `request_processor_service.py` or `backend_service.py` with inline branching.
**Why bad:** Recreates high-cyclomatic hotspots already identified by god-object analysis.
**Instead:** Add new collaborator interface + implementation; inject in stage wiring.

### Anti-Pattern 2: Connector Policy Drift
**What:** Embedding safety, command semantics, or routing policy inside connector modules.
**Why bad:** Policy becomes provider-dependent; behavior diverges across backends.
**Instead:** Keep connector code focused on provider protocol/auth/stream parsing only.

### Anti-Pattern 3: Cross-Boundary Untyped Dict Creep
**What:** Reintroducing `dict[str, Any]`/dynamic attributes across transport-core-connector seams.
**Why bad:** Hidden contract drift, weaker refactor safety, harder replay/debug determinism.
**Instead:** Extend canonical typed contracts and constrained extension fields.

### Anti-Pattern 4: Feature-by-Feature Stage Bypass
**What:** New controllers/services bypassing staged startup and DI registration conventions.
**Why bad:** Non-deterministic startup and brittle environment-specific behavior.
**Instead:** Register through existing stage + DI orchestration paths.

## Brownfield Evolution Guidance (specific)

1. **Stabilize seams before adding major capabilities**
   - Expand typed boundary coverage for highest-change paths (request processor internals, backend flow collaborators, streaming contracts).
   - Add architecture checks that reject provider-specific imports in core policy modules.

2. **Extract complexity by vertical slices, not massive rewrites**
   - For each hotspot (request processor, backend service, translation), carve out one bounded collaborator at a time with parity tests.
   - Keep behavior constant first, then optimize.

3. **Move connector-specific branching out of core via capability contracts**
   - Introduce explicit connector capability descriptors (stream semantics, tool-call shape, usage fidelity) and route behavior via capabilities, not backend-name conditionals.

4. **Create a protocol adaptation package split by boundary direction**
   - `frontend -> canonical` and `canonical -> backend` transformation sets should be independently testable.
   - This reduces blast radius when one protocol changes.

5. **Treat observability as architecture, not tooling**
   - Every new flow must define: correlation IDs, capture points, usage attribution, failure taxonomy.
   - “No capture/usage path” should block merge for core orchestration changes.

## Suggested Build Order for Hardening + Expansion (Roadmap Inputs)

1. **Boundary Hardening Phase** (first)
   - Goal: reduce regression risk while evolving brownfield architecture.
   - Work: typed contracts, collaborator extraction completion, deterministic boundary validation, architecture lint rules.
   - Why first: all expansion work depends on safe seams.

2. **Reliability Core Phase**
   - Goal: make backend lifecycle/failover behavior predictable under load and provider faults.
   - Work: failure recovery normalization, health-aware routing invariants, cancellation consistency, streaming resilience.
   - Dependency: requires stable boundaries from phase 1.

3. **Connector Plane Standardization Phase**
   - Goal: stop connector sprawl from infecting core.
   - Work: connector capability schema, shared connector mixins/tooling, plugin-path parity with in-tree connectors.
   - Dependency: reliability policies must already be centralized.

4. **Protocol Translation Decoupling Phase**
   - Goal: scale frontend/backend protocol variants without pairwise explosion.
   - Work: split large translation modules into directional adapters over canonical contracts; add contract tests across protocol matrix.
   - Dependency: connector capabilities and canonical contracts defined.

5. **Operational Control Plane Phase**
   - Goal: mature operator experience and safe live operations.
   - Work: diagnostic endpoints unification, reactivation/health controls, quota/usage surfaces, capture/replay workflows.
   - Dependency: earlier phases provide reliable telemetry and stable lifecycle hooks.

6. **Net-New Capability Expansion Phase**
   - Goal: add advanced features (new providers, richer agent controls) with bounded risk.
   - Work: only after previous architectural debt is constrained.

**Ordering rationale:** Hardening seams and failure semantics first prevents each new connector/protocol from multiplying complexity. Expansion before that likely reintroduces god objects and hidden coupling.

## Scalability Considerations

| Concern | At 100 users | At 10K users | At 1M users |
|---------|--------------|--------------|-------------|
| Orchestration complexity | Single-process flow acceptable | Extract hot-path collaborators + stricter contracts | Multi-node control plane with strict versioned contracts |
| Connector growth | In-repo connectors manageable | Capability registry + plugin packages needed | Fully contract-versioned connector ecosystem |
| Reliability/failover | Basic retry/failover enough | Health/rate-limit aware routing mandatory | Adaptive policy routing + backpressure + regional failover |
| Observability volume | Basic logs + selective capture | Structured capture sampling + indexed diagnostics | Tiered telemetry pipeline + replay stores + retention policies |
| Safety policy execution | Inline policy checks acceptable | Dedicated policy services and cache strategies | Distributed policy evaluation with deterministic audit trails |

## Sources

- `.planning/PROJECT.md` (brownfield goals, constraints, decisions) — HIGH
- `README.md` (supported fronts/backends, product intent, ops surfaces) — HIGH
- `.kiro/steering/tech.md` (staged init order, DI boundaries, processor/backend flow contracts) — HIGH
- `.kiro/steering/structure.md` (component map, ownership by path, startup lifecycle) — HIGH
- `docs/development_guide/typed-data-contracts.md` (canonical contracts and boundary conversion policy) — HIGH
- `docs/development_guide/plugin-api.md` (extension and plugin compatibility contract) — HIGH
- `docs/development_guide/god-objects-report.md` (brownfield complexity hotspots and refactor risk) — MEDIUM (internal static-analysis report)
