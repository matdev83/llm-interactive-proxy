# Research & Design Decisions

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Usage**:
- Log research activities and outcomes during the discovery phase.
- Document design decision trade-offs that are too detailed for `design.md`.
- Provide references and evidence for future audits or reuse.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `openai-codex-connector-god-object-refactoring`
- **Discovery Scope**: Extension
- **Key Findings**:
  - `src/connectors/openai_codex.py` concentrates auth, payload building, streaming, compatibility, and tool execution; splitting is required to reduce risk and improve test seams.
  - Credential handling uses a strict concurrency pattern (token refresh lock, atomic writes, event-based watcher gating) that must be preserved to avoid auth regressions.
  - Compatibility layer behavior (KiloCode XML parsing, Droid tool translation, passthrough detection, and tool schema collision handling) is already encoded and validated by tests; refactor must keep behavior stable while moving logic into smaller units.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/connectors/openai_codex.py` - connector facade and core logic
  - `src/connectors/_openai_codex_request_translator.py` - input item translation
  - `src/connectors/_openai_codex_capabilities.py` - capability resolution
  - `src/connectors/_openai_codex_kilo_tool_translator.py` - XML tool translation
  - `src/connectors/_openai_codex_droid_tool_translator.py` - Droid tool mapping
  - `src/connectors/_openai_codex_session_detector.py` - KiloCode detection
  - `src/connectors/_openai_codex_telemetry.py` - compatibility telemetry
  - `src/connectors/openai.py` - base OpenAI connector behaviors
  - `tests/integration/test_codex_kilo_compatibility_e2e.py` and `tests/codex/` - current test seams and expectations
  - `docs/user_guide/backends/openai-codex.md` and `src/connectors/knowledge.md` - documented behaviors and pitfalls
- **Patterns Identified**:
  - Connectors are registered via `backend_registry.register_backend` at module import time.
  - Asynchronous I/O and retry handling occur in connectors, not core services.
  - Compatibility layer branches are toggled by capability resolution and detection heuristics.
- **Implications**: The refactor must preserve module import registration, async I/O flows, and existing compatibility branching while extracting cohesive subcomponents.

### Credential Handling and Concurrency
- **Context**: Requirements 6.1 to 6.3 and documented warnings in `src/connectors/knowledge.md`.
- **Sources Consulted**: `src/connectors/openai_codex.py`, `src/connectors/knowledge.md`.
- **Findings**:
  - Credential reloads are gated by `_token_refresh_lock` and `threading.Event` to prevent races.
  - Refresh persistence uses atomic write patterns with `os.replace`.
  - File watcher triggers must schedule a single reload task per window.
- **Implications**: Credential responsibilities should move into a single component that owns locks and watcher coordination.

### Streaming Authentication Retry
- **Context**: Requirements 7.1 to 7.3.
- **Sources Consulted**: `src/connectors/openai_codex.py` streaming code.
- **Findings**:
  - Streaming retry has two entry points: handshake authentication failures and chunk-level auth errors.
  - Retry budget and backoff are configurable and must remain consistent.
- **Implications**: Streaming execution should be centralized in a component that owns retry policy and refresh sequencing.

### Compatibility Layer and Tool Translation
- **Context**: Requirements 1.2, 1.5, 2.3, 8.3.
- **Sources Consulted**: `_openai_codex_kilo_tool_translator.py`, `_openai_codex_droid_tool_translator.py`, `_openai_codex_session_detector.py`.
- **Findings**:
  - KiloCode translation uses XML parsing and tool execution via `UniversalToolExecutor` and MCP bridges.
  - Droid translation requires streaming chunk tool call translation and tool name cache state.
- **Implications**: Compatibility responsibilities should be grouped behind a dedicated interface with stable state ownership.

### Configuration and Documentation Parity
- **Context**: Requirement 9.1 and 9.2.
- **Sources Consulted**: `src/connectors/openai_codex.py`, `docs/user_guide/backends/openai-codex.md`.
- **Findings**:
  - Settings are composed from YAML and environment variables with explicit precedence.
  - Renderer and tool schema configuration have collision handling rules that must remain unchanged.
- **Implications**: A settings loader should remain the single source of truth for configuration normalization.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extracted Components | Keep `openai_codex.py` facade and move logic into new helper modules | Minimal behavior change, supports test seams | Facade can remain complex if extraction is shallow | Preferred baseline |
| New Connector Package | Move connector to `src/connectors/openai_codex/` package with a thin facade module | Strong boundaries, better file organization | Requires careful re-exports and test updates | Considered |
| Hybrid | Start with extracted components, then migrate to package layout | Balanced risk and clarity | Two-phase migration needed | Recommended |

## Design Decisions

### Decision: Connector facade plus internal component services
- **Context**: Requirements 2.x, 4.x, 8.x.
- **Alternatives Considered**:
  1. Keep monolith and only split utility functions
  2. Full rewrite into new connector package
- **Selected Approach**: Extract cohesive responsibilities into dedicated services while retaining a small `OpenAICodexConnector` facade.
- **Rationale**: Preserves import paths and registry behavior while enabling modular testing and incremental migration.
- **Trade-offs**: Slight overhead from delegating through more layers; requires adapter properties for legacy tests.
- **Follow-up**: Define stable interfaces for new components and document any attribute migration.

### Decision: Credential manager ownership of concurrency
- **Context**: Requirement 6.x and documented pitfalls.
- **Alternatives Considered**:
  1. Keep lock and watcher logic in the connector
  2. Centralize in a credential manager component
- **Selected Approach**: Centralize credential loading, refresh, and watcher scheduling in a single component.
- **Rationale**: Reduces race condition risk and keeps the connector facade thin.
- **Trade-offs**: Requires explicit API for access token retrieval and account metadata.
- **Follow-up**: Ensure thread-safe event gating and async task scheduling remain unchanged.

### Decision: Streaming retry policy extracted from connector
- **Context**: Requirement 7.x.
- **Alternatives Considered**:
  1. Keep streaming logic inside connector
  2. Create a dedicated response executor with retry policy
- **Selected Approach**: Response executor owns handshake and chunk retry logic, using a policy object for backoff.
- **Rationale**: Improves testability and isolates streaming behavior.
- **Trade-offs**: Additional component boundaries; must preserve exact error shapes.
- **Follow-up**: Add targeted tests for handshake and mid-stream auth failures.

### Decision: Interface-first contracts for component boundaries
- **Context**: Requirement 3.2, 4.3, design principles on type safety.
- **Alternatives Considered**:
  1. Use concrete classes only
  2. Define interfaces for key boundaries
- **Selected Approach**: Define small ABC-style interfaces for settings, credentials, payload, response execution, and compatibility services.
- **Rationale**: Enables DI and test seams without coupling components.
- **Trade-offs**: Extra boilerplate and interface maintenance.
- **Follow-up**: Keep interfaces in connector-local namespace to avoid core coupling.

### Decision: DI Lifetime Selection
- **Context**: Selecting between Singleton, Scoped, and Transient lifetimes.
- **Selected Approach**: Singleton lifetime for connector components because they are stateless or internally synchronized and live with the connector instance.
- **Rationale**: Matches connector lifecycle and avoids per-request allocations.

### Decision: Error Handling Strategy
- **Context**: Requirement 1.3 and error model in steering.
- **Selected Approach**: Preserve existing HTTPException and `LLMProxyError` mapping behavior; do not introduce new error types unless required by new interfaces.
- **Rationale**: Guarantees backward compatibility with current error handlers and tests.

## Testing Strategy Research

### Existing Test Patterns
- Integration tests in `tests/integration/test_codex_kilo_compatibility_e2e.py` validate KiloCode flows.
- Codex-specific unit tests under `tests/codex/` validate Droid translators and detectors.
- Tests access internal connector fields for setup, so adapter properties are required during migration.

### Coverage Requirements
- Credential reload and refresh concurrency paths
- Streaming authentication retry behavior
- Tool schema collision handling and passthrough detection
- Compatibility layer behavior for KiloCode and Droid clients

## Risks & Mitigations
- Risk 1: Credential race regressions - Mitigation: keep lock ownership within credential manager and add concurrency tests.
- Risk 2: Streaming auth retry drift - Mitigation: isolate retry policy and assert error shapes in tests.
- Risk 3: Test breakage due to internal attribute moves - Mitigation: provide adapter properties and update tests incrementally.

## Performance Considerations
- Async I/O remains in connector executor paths; no new network calls are introduced.
- Added indirection should be negligible; critical paths avoid extra allocations in streaming loops.
- Wire capture payloads and logging remain unchanged.

## References
- `src/connectors/openai_codex.py`
- `src/connectors/_openai_codex_request_translator.py`
- `src/connectors/_openai_codex_capabilities.py`
- `src/connectors/_openai_codex_kilo_tool_translator.py`
- `src/connectors/_openai_codex_droid_tool_translator.py`
- `src/connectors/_openai_codex_session_detector.py`
- `src/connectors/knowledge.md`
- `docs/user_guide/backends/openai-codex.md`
