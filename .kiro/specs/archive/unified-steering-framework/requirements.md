# Requirements Document

## Introduction
We need a unified steering framework that removes duplicated command parsing and session tracking across tool call handlers while preserving current steering behaviors and telemetry. The system should centralize steering decisions through a prioritized policy chain, expose a reusable TTL/LRU session state store, and maintain compatibility with existing configurations and logging.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining steering/guardrail behaviors for tool calls
- Operators relying on consistent telemetry and configuration controls
- Users of automated agents whose tool calls must be steered safely

## Requirements

### Requirement 1: Unified Steering Entry Point
**Objective:** As a platform maintainer, I want a single steering entry point to evaluate tool-call commands via a prioritized policy chain, so that steering behavior is consistent, traceable, and easier to extend.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When a tool call with command arguments arrives, the system shall extract and normalize the command string once and pass it through a deterministic priority-ordered policy chain until the first match returns a result.
2. If no policy returns a result, then the system shall fall back to existing default behavior (no steering) without raising errors.
3. While policies run, the system shall emit a single structured telemetry/log entry per evaluated tool call capturing handler name, matched policy (or none), and decision outcome.
4. When multiple policies could match, the system shall enforce the configured priority order to choose the first match, preserving current observable steering outcomes.
5. The system shall expose a configuration point to set or override policy order without code changes.

#### Technical Constraints
- Async compatibility: Must use `async/await`; policies execute without blocking the event loop.
- DI integration: Unified handler registered via `ServiceCollection`; policies resolved through DI.
- Error hierarchy: Steering errors extend `LLMProxyError` or use existing steering error types.
- Config precedence: CLI > ENV > YAML applies to policy ordering/config toggles.

### Requirement 2: Shared Session State Store
**Objective:** As a developer, I want a reusable TTL/LRU session state store for steering policies, so that duplicate pruning/TTL logic is eliminated and state handling is consistent.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When policies request session state by key, the store shall return an isolated state bucket per session/tool context without leaking across sessions.
2. When entries exceed the configured TTL, the store shall evict them lazily on access and/or via periodic pruning to avoid stale steering decisions.
3. When the number of sessions exceeds the configured max, the store shall evict the least recently used sessions first.
4. The store shall expose configuration for TTL duration and max sessions; defaults must maintain parity with existing handlers’ behavior.
5. The store’s operations shall be safe under concurrent async access without data corruption.

#### Technical Constraints
- Implemented as an async-safe component; no blocking locks.
- DI-registered singleton or scoped according to existing steering lifecycle; configurable via app config.
- Logging compatible with existing steering telemetry (redacted where needed).

### Requirement 3: Policy Parity and Migration
**Objective:** As an operator, I want existing steering behaviors (inline python steering, pytest full-suite reminder, configured rules) preserved after migration, so that no regressions occur for current users.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When InlinePython, Pytest full-suite, or Configured Rules steering conditions are met, the unified system shall produce the same steering prompts/actions as before (content, severity/level, blocking behavior).
2. While migrating, the system shall reuse shared command parsing and session store without changing externally visible responses for matched policies.
3. When test execution reminder TTL/session logic applies, the outcomes (reminder frequency and expiry) shall remain identical to previous behavior given the same configuration.
4. Telemetry/log message formats and keys used by monitoring shall remain stable or provide compatibility shims documented in the design.
5. The migration shall include a fallback/feature flag to disable the unified handler and revert to legacy handlers if needed.

#### Technical Constraints
- Maintain existing config names/paths unless explicitly updated with backward-compatible defaults.
- Ensure compatibility with `ToolCallReactorMiddleware` response structures.
- Follow existing logging schema; avoid breaking dashboards.

### Requirement 4: Extensibility and Testing
**Objective:** As a maintainer, I want adding new steering policies to require minimal boilerplate and come with guardrail tests, so that future rules can be implemented quickly and safely.

**Priority:** P2 (Medium)

#### Acceptance Criteria
1. When a new policy implements the `ISteeringPolicy` interface, the unified handler shall be able to register and evaluate it without additional orchestration code.
2. The design shall include interface documentation or examples showing how to add a new policy with configuration hooks.
3. Unit tests shall cover priority ordering, no-match paths, and concurrent session state interactions.
4. Migration tests shall assert parity for existing policies (InlinePython, Pytest full-suite, Configured Rules) across typical and edge-case inputs.
5. CI commands for the relevant test subset shall be documented (or automated) to verify steering behavior.

#### Technical Constraints
- Tests use async-friendly patterns; avoid sleep-based timing.
- Prefer property-based or table-driven cases for policy ordering and eviction where practical.

## Non-Functional Requirements

### NFR 1: Performance
- Command extraction and policy evaluation shall add no more than a negligible overhead versus current handlers (target within existing latency budget for tool call reactions).
- Session store operations shall be O(1) for typical access/eviction paths.

### NFR 2: Reliability
- Unified handler shall degrade gracefully if a policy raises; errors are contained and logged, and remaining policies or default behavior still proceed where safe.
- Eviction/TTL should not cause unhandled exceptions; pruning is safe to skip if it fails.

### NFR 3: Observability
- Structured logs include policy name, outcome, and timing; redaction applied to command content consistent with current practice.
- Metrics (if present) remain compatible with existing dashboards or are documented for migration.

### NFR 4: Security
- Command parsing and logging must avoid emitting sensitive command content in plaintext where current system redacts.
- Input validation remains consistent with existing steering handlers to avoid expanding execution surface.

## Glossary
| Term | Definition |
|------|------------|
| Steering | Logic that inspects tool-call commands and returns guidance or blocking responses |
| Policy | A discrete rule implementing `ISteeringPolicy` to evaluate a command and optionally steer |
| Session State Store | TTL/LRU-managed state container used by steering policies (e.g., reminders) |
| Tool Call | Agent-invoked command/tool execution request passing through the steering middleware |
