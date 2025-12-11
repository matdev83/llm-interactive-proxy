# Design Document

---
**Purpose**: Consolidate steering into a unified, policy-driven handler with shared session state while preserving existing behaviors and telemetry.
**Project Context**: Universal LLM Proxy - FastAPI async service with staged initialization, DI containers, adapter pattern for LLM backends.
---

## Overview
The feature delivers a unified steering handler that normalizes tool-call commands once, evaluates a prioritized policy chain (inline python, pytest full-suite reminder, configured rules), and produces consistent steering outcomes with centralized telemetry. Target users are platform maintainers and operators who need predictable, observable steering; agent users benefit from consistent guidance without regressions. The change replaces multiple duplicated handlers with a single entry point and shared session state store to simplify maintenance and extensibility.

### Goals
- One command extraction path and one deterministic policy pipeline per tool call.
- Shared async-safe TTL/LRU session store reused by policies.
- Preserve existing steering outputs, config surfaces, and telemetry formats.
- Make adding new policies low-boilerplate via `ISteeringPolicy`.

### Non-Goals
- Introducing new steering behaviors beyond policy migration.
- Changing existing config names or telemetry schemas (beyond compatibility shims).
- Modifying ToolCallReactorMiddleware response envelopes.

## Architecture

### Existing Architecture Analysis
- Current handlers (InlinePythonSteeringHandler, PytestFullSuiteHandler, ConfigSteeringHandler) each parse commands and manage their own state, causing duplication and inconsistent priority handling.
- Session TTL/pruning logic is duplicated across Pytest full-suite and reminder flows.
- Steering registration is scattered, making priority ordering implicit.

### Architecture Pattern & Boundary Map
- Pattern: Policy Chain (priority-ordered) within a Unified Steering Handler.
- Domain boundaries: Steering remains a middleware/handler concern; session store is a shared utility.
- Existing patterns preserved: async-first, DI-based service registration, staged init.
- New components rationale: `UnifiedSteeringHandler` centralizes orchestration; `ISteeringPolicy` standardizes policy contracts; `SessionStateStore` provides reusable TTL/LRU state.

### Technology Stack

| Layer | Choice / Version | Role in Feature | Notes |
|-------|------------------|-----------------|-------|
| Runtime | Python 3.10+ / FastAPI (async) | Handler execution | Use `async/await` |
| DI Container | `src/core/di/container.py` | Resolve handler + policies | Policies registered as services |
| Initialization | Staged (`src/core/app/stages/`) | Register handler/policies | Preserve existing stage ordering |
| Config | `src/core/config/app_config.py` | Policy order & toggles | CLI > ENV > YAML precedence |

## System Flows

Sequence (simplified):
1. Tool call arrives at UnifiedSteeringHandler.
2. Command extraction/normalization runs once (shared helper).
3. For each policy in configured priority:
   - `policy.evaluate(context, command)` returns `SteeringResult | None`.
   - First non-None result short-circuits.
4. If no policy matches, handler yields default pass-through.
5. Telemetry emitted once with evaluated policies, match/no-match, outcome, timing.

## Requirements Traceability

| Requirement | Summary | Components | Interfaces | Flows |
|-------------|---------|------------|------------|-------|
| 1 | Unified steering entry point with priority | UnifiedSteeringHandler, policy chain | IToolCallHandler, ISteeringPolicy | Sequence above |
| 2 | Shared session state store TTL/LRU | SessionStateStore | SessionStateStore API | Policy evaluate paths |
| 3 | Policy parity/migration | InlinePythonPolicy, PytestFullSuitePolicy, ConfiguredRulesPolicy | ISteeringPolicy | Policy chain |
| 4 | Extensibility/testing | ISteeringPolicy contract, tests | ISteeringPolicy | Sequence & tests |

## Components and Interfaces

**DI Registration Strategy**
- `UnifiedSteeringHandler`: registered as the steering IToolCallHandler (Singleton).
- Policies: registered individually (Singleton) and injected as an ordered list (configurable order).
- `SessionStateStore`: Singleton shared across policies.

### Services / Handlers

#### UnifiedSteeringHandler (`src/services/steering/unified_steering_handler.py`)
| Field | Detail |
|-------|--------|
| Intent | Single entry point for tool-call steering via ordered policies |
| Requirements | 1, 3, 4 |
| Interface | `IToolCallHandler` |
| DI Lifetime | Singleton |

Responsibilities & Constraints
- Extract/normalize command once; short-circuit on first policy result.
- Emit one telemetry/log entry per tool call with policy evaluations.
- Handle policy errors gracefully (log, continue unless critical).

Dependencies (via DI)
- Ordered list of `ISteeringPolicy`
- Telemetry/logging utilities
- Config provider for policy ordering/flags

Contracts: Middleware/Handler ✓

#### ISteeringPolicy (`src/services/steering/interfaces.py`)
| Field | Detail |
|-------|--------|
| Intent | Contract for steering policies |
| Requirements | 1, 4 |
| DI Lifetime | Implementations singleton |

Interface
```python
class ISteeringPolicy(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def evaluate(self, context: ToolCallContext, command: str) -> SteeringResult | None:
        """Return steering result if policy triggers; otherwise None."""
```
- Preconditions: command normalized string.
- Postconditions: return None or SteeringResult; no side effects beyond telemetry/state.

#### SteeringResult (`src/services/steering/models.py`)
- Intent: Structured outcome with message/content, severity/level, and metadata (matched policy name, flags).
- Requirements: 1, 3.

#### SessionStateStore (`src/services/steering/session_state_store.py`)
| Field | Detail |
|-------|--------|
| Intent | Async-safe TTL + LRU store for per-session policy state |
| Requirements | 2 |
| DI Lifetime | Singleton |

Responsibilities & Constraints
- Per-session buckets; lazy eviction on access plus optional periodic prune hook.
- Configurable TTL and max sessions; defaults match existing behavior.
- Async-safe operations; avoid blocking locks.

### Policies (migrated)

#### InlinePythonPolicy
- Requirements: 1, 3.
- Behavior: Match inline python execution commands; steer per legacy logic.
- Dependencies: command parser helper.

#### PytestFullSuitePolicy
- Requirements: 1, 2, 3.
- Behavior: Uses SessionStateStore for TTL/reminder frequency; matches full-suite invocations.
- Dependencies: SessionStateStore, command parser.

#### ConfiguredRulesPolicy
- Requirements: 1, 3.
- Behavior: Uses existing configured rules to match/steer commands.
- Dependencies: config rules, command parser.

## Data Models
- `SteeringResult`: message/content, severity/level, metadata (policy name, action), optional flags for blocking/allow.
- Session state entries: `{ last_seen: datetime, payload: policy-specific data }` with TTL and LRU metadata.

## Error Handling
- Policy errors caught per evaluation; logged with `exc_info=True`; handler continues to next policy unless configured to halt.
- Use existing steering/LLMProxyError hierarchy; avoid bare exceptions.

## Testing Strategy
- Unit tests: policy priority ordering, no-match path, telemetry emission, error containment.
- Session store tests: TTL eviction, LRU eviction, concurrent async access, config defaults parity with legacy.
- Migration parity tests: InlinePython, Pytest full-suite, Configured rules produce identical outcomes for representative cases.
- Commands:
  - Fast subset: `./.venv/Scripts/python.exe -m pytest tests/steering -k "unified or policy" -v`
  - Full (if required): `./.venv/Scripts/python.exe -m pytest -m "integration or unit"`

## Stage Registration
- Register SessionStateStore and policies in existing steering stage (same stage currently registering steering handlers).
- Replace legacy handlers with UnifiedSteeringHandler wiring; keep feature flag to toggle legacy path if needed.

## Supporting References (if needed)
- Legacy behavior parity documented in migration tests and comments; telemetry key compatibility noted in code.***
