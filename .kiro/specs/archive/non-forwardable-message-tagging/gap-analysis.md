# Gap Analysis: Non-Forwardable Message Tagging

## Executive Summary

The current codebase has a mature command pipeline, request preparation (including history compaction), and a centralized backend orchestration flow (`BackendCompletionFlow`). However, non-forwardable behavior is presently enforced through regex-based redaction and metadata-dependent heuristics, with fail-open semantics and multiple backend-call bypasses. There is no session-scoped tag registry or deterministic identity service, and compaction can rewrite tool output content without any mechanism to preserve non-forwardable matching.

**Primary evidence**:
- Command stripping and proxy response removal are implemented in `src/core/services/redaction_middleware.py` using regex (`src/security.py::ProxyCommandFilter`) and metadata (`metadata.is_proxy_response`), which does not survive client history re-submission.
- Backend calls bypassing the central flow exist (e.g., `src/codebuff/handlers/prompt_handler.py`, `src/connectors/hybrid_backend/infrastructure/phase_executor.py`).
- History compaction rewrites tool result content in `src/core/services/backend_request_preparation_service.py` via `HistoryCompactionService`, but no identity-based tag persistence exists.

**Effort**: L (1–2 weeks)  
**Risk**: Medium (cross-cutting integration + removal of legacy behavior)

## 1. Current State Investigation

### Key assets already in place

- **Request processing orchestration**:
  - `src/core/services/request_processor_service.py` orchestrates command handling, request prep, transforms, and backend execution.
- **Command pipeline**:
  - `src/core/services/command_handler.py` + `src/core/services/command_processor.py`
  - `src/core/commands/service.py` parses and executes commands, modifies message content to strip command text.
- **Backend orchestration and wire capture**:
  - `src/core/services/backend_completion_flow/service.py` centralizes backend call orchestration and wire capture ordering.
- **History compaction**:
  - `src/core/services/backend_request_preparation_service.py` invokes `HistoryCompactionService`, which may rewrite tool result content.
- **Session management**:
  - Session resolution via `ISessionManager`/`ISessionResolver` (e.g., `DefaultSessionResolver`, `IntelligentSessionResolver`), with `SessionService` storing `SessionState`.
- **Structured logging / capture**:
  - Wire capture in `BackendCompletionFlow` captures outbound and inbound payloads.

### Existing enforcement & legacy behavior

- **Regex-based filtering**:
  - `src/security.py::ProxyCommandFilter` uses regex to remove proxy commands from text.
  - `src/core/services/redaction_middleware.py` applies this filter and removes proxy response pairs based on `metadata.is_proxy_response`.
- **Fail-open semantics**:
  - `RequestTransformPipeline` and history compaction catch errors and continue.
- **Backend-call bypasses**:
  - `src/codebuff/handlers/prompt_handler.py` calls `backend.chat_completions(...)` directly.
  - `src/connectors/hybrid_backend/infrastructure/phase_executor.py` calls `execution_connector.chat_completions(...)` directly.
  - `src/core/app/controllers/__init__.py` has a test-only shortcut using `app_state.openrouter_backend.chat_completions(...)`.

### Integration surfaces

- **Message models**: `src/core/domain/chat.py` (message roles, tool_call_id, tool_calls).
- **Request context**: `src/core/domain/request_context.py` supports `extensions` for internal provenance.
- **Compaction identity hints**: `src/core/services/history_compaction_service.py` uses `tool_call_id` to correlate tool result messages.

## 2. Requirement-to-Asset Map (with Gaps)

| Requirement | Existing Assets | Gaps / Constraints |
|------------|------------------|-------------------|
| 1.x Session-scoped tagging + identity | Session services; message models; RequestContext extensions | No tag registry; no deterministic identity service; no immutability guarantees; no tag persistence across requests. |
| 2.x Slash commands never forwarded | Command parser/handler pipeline | Commands are removed from content but not tagged; regex-based filtering is the only enforcement and does not survive history resubmission. |
| 3.x Command responses never forwarded | ResponseManager adds `metadata.is_proxy_response` | Metadata is not preserved by clients; no identity-based tagging; relies on RedactionMiddleware removal. |
| 4.x Steering/internal messages not client-forwardable | Tool-call steering and retry flows (e.g., `tool_call_retry_coordinator`, loop breaking services) | Steering injections are not tagged; no provenance boundary to distinguish injected messages vs. client history. |
| 5.x Filtering across protocols/roles | RequestTransformPipeline; backend completion flow | Filtering is currently role-limited and performed in redaction middleware; not enforced at the backend-call boundary. |
| 6.x Observability | Structured logging + wire capture | No dedicated log for filtered counts or tag-based filtering decisions. |
| 7.x Single enforcement point | BackendCompletionFlow provides a central boundary | Bypass call sites exist; enforcement is not currently wired into BackendCompletionFlow. |
| 8.x Session identity coverage | Session manager/resolvers for HTTP flows | Non-HTTP entry points may not resolve/create session_id; CompletionSessionResolver can return None. |
| 9.x Performance | Existing async pipeline | Identity computation and registry lookups do not exist; needs caching/batching strategy. |
| 10.x Reliability (fail-closed) | LLMProxyError hierarchy | Redaction and compaction fail-open; no fail-closed path for non-forwardable matching. |
| 11.x Observability (telemetry correlation) | Structured logging + capture | No log field for filtered counts/correlation of tag filtering decisions. |
| 12.x Security (spoof resistance) | Client metadata not trusted in theory | Current removal uses `metadata.is_proxy_response`; clients can omit/modify this; no server-only registry. |
| 13.x Legacy removal | Redaction middleware + ProxyCommandFilter exist | Regex-based mechanisms must be removed, not just bypassed. |
| 14.x Bounded tag storage | None | Requires new storage mechanism with dedupe and configurable limit. |

## 3. Implementation Approach Options

### Option A: Extend existing redaction/command mechanisms
**Description**: Expand `RedactionMiddleware` and command pipeline to tag and filter messages, and attempt to enforce filtering within `RequestTransformPipeline`.

**Pros**:
- Minimal new services and files.
- Uses existing middleware and command pipeline wiring.

**Cons**:
- `RequestTransformPipeline` is fail-open and not the final backend boundary.
- Requires significant refactor to make middleware fail-closed and robust across all entry points.
- Conflicts with requirement 13.x (legacy regex removal).

### Option B: Create new tagging services + enforce at backend boundary (Option B)
**Description**: Introduce new identity/registry/enforcer services, wire them into `BackendCompletionFlow` immediately before outbound capture and invocation. Tag at sources (command handler, response manager, steering injectors). Route all backend calls through the shared orchestrator.

**Pros**:
- Aligns with requirement 7.x single enforcement point and fail-closed behavior.
- Isolated, testable services with clear responsibilities.
- Handles compaction safely by defining identity rules that do not depend on tool output content.

**Cons**:
- Requires integration changes across multiple layers (command pipeline, steering, backend flow).
- Requires removal of legacy regex mechanisms and updates to tests.

### Option C: Hybrid (new enforcement + phased refactor of entry points)
**Description**: Add new tagging/enforcer services and wire into `BackendCompletionFlow`, but refactor bypasses and legacy removal in phases.

**Pros**:
- Allows staged adoption for non-HTTP entry points.
- Reduces initial integration risk.

**Cons**:
- Risk of temporary inconsistencies across entry points (disallowed if fallbacks remain).
- Requires careful sequencing to avoid policy drift.

## 4. Implementation Complexity & Risk

- **Effort: L (1–2 weeks)** — new services, config, errors, and integration changes across backend flow, command pipeline, steering injections, and entry points.
- **Risk: Medium** — behavior changes in command handling and backend-call routing; removal of regex-based mechanisms could impact legacy tests and implicit behaviors.

## 5. Recommendations for the Design Phase (Information, not final decisions)

### Likely preferred approach
- **Option B** aligns with requirements and reduces surface for bypasses. It also enables deterministic identity rules for compaction compatibility and supports explicit memory bounds.

### Research Needed (carry into design)

1. **Tag storage location**: decide whether to store tags in session state, a dedicated session-scoped repository, or a new in-memory registry with persistence options.
2. **Identity canonicalization**: confirm which message fields are stable across protocol translations and compaction (especially tool result handling via `tool_call_id`).
3. **Entry-point coverage**: enumerate all non-HTTP backend call paths and ensure they can pass `RequestContext.session_id` to the shared orchestrator.
4. **Steering injection boundary**: identify all components that inject steering/internal messages (tool-call retry, loop breaking, test execution reminder) and define the provenance boundary required for `client_history_only` behavior.
5. **Legacy removal scope**: list all regex-based non-forwardable filters and related tests/fixtures to remove (e.g., `ProxyCommandFilter`, `RedactionMiddleware` command stripping, `metadata.is_proxy_response` usage).
