# Typed Contract Boundaries and Enforcement

This guide describes the project's strategy for hardening cross-layer data exchange using canonical typed contracts. It defines what constitutes a "boundary surface," how to use the canonical contracts, and how to maintain compliance with the boundary type guardrails.

## Overview

The Universal LLM Proxy uses a layered architecture where data flows between:
1.  **Transport Layer** (HTTP/FastAPI controllers, adapters)
2.  **Core Services** (Request processing, orchestration, accounting)
3.  **Connectors** (Provider-specific implementations)

To ensure stability, debuggability, and type safety, these cross-layer seams must exchange **canonical typed contracts** rather than ad-hoc `dict[str, Any]` payloads.

### Goals
-   **Stable Contracts:** Core services rely on explicit Pydantic models or dataclasses.
-   **Zero Dict Leaks:** `dict[str, Any]` is forbidden at boundary signatures.
-   **JSON Safety:** Extension fields crossing boundaries must be JSON-serializable (`JsonValue`).
-   **Enforcement:** Automated tools prevent regression.

## Canonical Contract Set

Use these contracts for data exchange across boundaries.

| Concept | Canonical Contract | Module |
| :--- | :--- | :--- |
| **Request** | `CanonicalChatRequest` | `src.core.domain.chat` |
| **Context** | `RequestContext` | `src.core.domain.request_context` |
| **Connector Context** | `ConnectorRequestContext` | `src.connectors.contracts` |
| **Target** | `BackendTarget` | `src.core.domain.backend_target` |
| **Usage** | `UsageSummary` | `src.core.domain.usage_summary` |
| **Response** | `ResponseEnvelope` | `src.core.domain.responses` |
| **Stream** | `StreamingResponseEnvelope` | `src.core.domain.responses` |
| **Stream Chunk** | `ProcessedResponse` | `src.core.interfaces.response_processor_interface` |
| **Connector Input** | `ConnectorChatCompletionsRequest` | `src.connectors.contracts` |

## Extension Mechanisms Policy

### Approved vs Legacy Extension Mechanisms

The project maintains a clear distinction between **approved** extension mechanisms (for new code) and **legacy** mechanisms (allowed for backward compatibility only).

#### Approved Extension Mechanisms (JSON-Safe)

Use these mechanisms for **new** cross-layer extensibility. All extension values must be `JsonValue` (JSON-serializable):

*   **`RequestContext.extensions: dict[str, JsonValue]`**: For cross-layer context metadata
*   **`ConnectorRequestContext.extensions: dict[str, JsonValue]`**: For connector-facing context metadata
*   **`UsageSummary.extensions: dict[str, JsonValue]`**: For provider-specific usage data
*   **`ResponseEnvelope.metadata: dict[str, JsonValue] | None`**: For response metadata crossing seams
*   **`StreamingResponseEnvelope.metadata: dict[str, JsonValue] | None`**: For streaming response metadata
*   **`ProcessedResponse.metadata: dict[str, JsonValue]`**: For streaming processed-chunk metadata crossing core → transport seam

**Key Requirements**:
*   All extension values must be `JsonValue` (JSON-serializable)
*   This ensures deterministic logging, wire capture, and replay
*   Type checkers can validate JSON-serializable constraint

#### Legacy Extension Mechanisms (No New Usage)

The following mechanisms exist for **backward compatibility only** and should **not** be used for new features:

*   **`ChatRequest.extra_body: dict[str, Any] | None`**: Allowed for protocol compatibility, but prefer typed fields where possible
*   **`ToolCall.extra_content: dict[str, Any] | None`**: Allowed for provider-specific tool artifacts
*   **`StreamingChunk.payload.opaque_json_dict: dict[str, Any] | None`**: Allowed as an explicit "opaque" escape hatch for non-standard streaming payloads

**Important**: These legacy mechanisms are kept for compatibility but have a documented promotion path requirement. When a stable, recurring concept is carried via a legacy mechanism, it must be promoted into a typed field or approved JSON-safe extension mechanism on a time-bounded plan.

### Forbidden Patterns

The following patterns are **explicitly forbidden** at boundary surfaces:

1. **New `dict[str, Any]` fields on boundary-carried contracts/envelopes**:
   ```python
   # FORBIDDEN: Adding new dict[str, Any] fields
   class ResponseEnvelope:
       metadata: dict[str, JsonValue] | None  # ✅ Approved
       custom_data: dict[str, Any]  # ❌ Forbidden
   ```

2. **New `metadata: dict[str, Any]` arguments on boundary Protocols/interfaces**:
   ```python
   # FORBIDDEN: Using dict[str, Any] for metadata
   def process_response(
       response: ResponseEnvelope,
       metadata: dict[str, Any]  # ❌ Forbidden
   ) -> ProcessedResponse:
       ...
   
   # CORRECT: Using dict[str, JsonValue]
   def process_response(
       response: ResponseEnvelope,
       metadata: dict[str, JsonValue] | None  # ✅ Approved
   ) -> ProcessedResponse:
       ...
   ```

3. **New `**kwargs: Any` usage outside the connector invoker/legacy connector compatibility surface**:
   ```python
   # FORBIDDEN: Using **kwargs at boundary
   def process_request(
       request: CanonicalChatRequest,
       **kwargs: Any  # ❌ Forbidden
   ) -> ResponseEnvelope:
       ...
   
   # CORRECT: Use explicit parameters or approved extension mechanism
   def process_request(
       request: CanonicalChatRequest,
       context: RequestContext  # ✅ Uses approved extensions
   ) -> ResponseEnvelope:
       ...
   ```

4. **Dynamic attribute assignment on boundary contracts**:
   ```python
   # FORBIDDEN: Dynamic attribute assignment
   context.custom_field = value  # ❌ Forbidden
   
   # CORRECT: Use approved extension mechanism
   context.extensions["custom_field"] = value  # ✅ Approved (if JsonValue)
   ```

### Promotion Guide

When extension keys become stable and frequently used, they should be **promoted** to first-class typed fields or moved to approved extension mechanisms.

#### Promotion Criteria

An extension key should be promoted when:

1. **Stability**: Field shape has been stable for multiple releases
2. **Frequency**: Field is accessed in multiple places across layers
3. **Semantic Importance**: Field affects core contract semantics or correctness
4. **Type Safety**: Stronger typing would catch bugs or improve maintainability

#### Promotion Examples

**Example 1: Stable Recurring Key → Typed Field**

**Before** (using extension):
```python
# Writers
context.extensions["backend"] = "openai"

# Readers
backend = context.extensions.get("backend")
```

**After** (promoted to typed field):
```python
# Contract definition
class RequestContext:
    backend: str | None = None
    extensions: dict[str, JsonValue] = field(default_factory=dict)

# Writers
context.backend = "openai"

# Readers
backend = context.backend
```

**Migration** (support both during transition):
```python
# Writers: use typed field
context.backend = "openai"

# Readers: check typed field first, fall back to extension for compatibility
backend = context.backend or context.extensions.get("backend")
```

**Example 2: Provider-Specific/Variable Key → Approved JSON-Safe Extension Mechanism**

**Scenario**: You need to pass provider-specific configuration that varies by backend.

**Correct Approach**:
```python
# Use approved extension mechanism
context.extensions["openai_service_tier"] = "priority"  # ✅ JsonValue
context.extensions["gemini_generation_config"] = {"temperature": 0.7}  # ✅ JsonValue

# Access via extension
tier = context.extensions.get("openai_service_tier")
```

**Incorrect Approach**:
```python
# FORBIDDEN: Adding new dict[str, Any] field
class RequestContext:
    provider_config: dict[str, Any]  # ❌ Forbidden
```

**Example 3: "Opaque JSON Blob" → Explicitly Named Opaque Field**

**Scenario**: You need to pass non-standard streaming payload data that doesn't fit standard types.

**Legacy Approach** (allowed for compatibility):
```python
# Legacy mechanism (no new usage)
chunk.payload.opaque_json_dict = {"custom": "data"}  # ⚠️ Legacy only
```

**Preferred Approach** (for new code):
```python
# Use approved extension mechanism if possible
processed_response.metadata["custom_payload"] = {"custom": "data"}  # ✅ JsonValue

# Or promote to typed field if stable
class StreamingPayload:
    custom_data: dict[str, JsonValue] | None = None  # ✅ Typed field
```

### Connector Options Policy

Connector options must follow a strict policy to ensure JSON-safety and type safety:

**Canonical Connector API**:
*   The canonical connector API (`ICanonicalChatCompletionsBackend`) takes `options: dict[str, JsonValue]` in `ConnectorChatCompletionsRequest`
*   All connector options must be JSON-serializable (`JsonValue`)
*   Options are explicitly tracked and validated

**Legacy Connector Compatibility**:
*   Legacy `**kwargs` expansion happens **only** inside `ConnectorInvoker` (the compatibility adapter)
*   This is a documented boundary exception with a deprecation note
*   Legacy connectors may accept `**kwargs`, but core orchestration always passes canonical contracts

**Migration Path**:
1. **Current State**: Legacy connectors accept `**kwargs` via `ConnectorInvoker` compatibility path
2. **Migration**: Update connector to implement `ICanonicalChatCompletionsBackend` and use `request.options`
3. **Future**: Legacy kwargs expansion will be deprecated and eventually removed

**Example**:
```python
# Canonical connector API (preferred)
async def chat_completions(
    self,
    request: ConnectorChatCompletionsRequest,
) -> ResponseEnvelope:
    # Access options via typed contract
    api_key = request.options.get("api_key")
    # ...

# Legacy connector (compatibility path)
async def chat_completions(
    self,
    request_data: CanonicalChatRequest,
    **kwargs: Any  # ⚠️ Legacy only, handled by ConnectorInvoker
) -> ResponseEnvelope:
    # Options expanded from request.options by ConnectorInvoker
    api_key = kwargs.get("api_key")
    # ...
```

## `Any` Policy: Internal-Only Allowance vs Boundary Prohibition

The project maintains a clear policy on where `Any` is permitted (internal-only contexts) and where it is forbidden (boundary surfaces).

### Where `Any` is Permitted (Internal-Only)

`Any` is **permitted** in the following contexts, which are **not** considered boundary surfaces:

1. **Internal Implementation Details**:
   *   Code within a single layer that doesn't cross boundaries
   *   Internal utilities and helper functions
   *   Example: Internal middleware processing raw provider responses before normalization

2. **Test Utilities and Fixtures**:
   *   Test code that doesn't test boundary contracts
   *   **Note**: Tests that verify boundary behavior should use canonical contracts

3. **Internal Processing Boundaries**:
   *   Middleware that processes raw provider responses before normalization
   *   Internal transformation pipelines that operate on untyped data before converting to contracts
   *   Example: `IResponseProcessor.process()` accepts `Any` for raw provider responses (internal processing)

4. **Serialization/Deserialization Methods**:
   *   Methods that convert between JSON/dict and typed contracts
   *   Example: `UsageSummary.from_dict()` accepts `dict[str, Any]` for JSON parsing
   *   Example: `UsageSummary.to_dict()` returns `dict[str, Any]` for JSON serialization

5. **Diagnostic/Logging Utilities**:
   *   Utilities that accept arbitrary data for logging or debugging
   *   Example: `RequestContext.get_modification_summary()` returns `dict[str, Any]` for diagnostics

**Key Principle**: If code doesn't cross a layer boundary (Transport ↔ Core ↔ Connector), `Any` may be acceptable for internal implementation flexibility.

### Where `Any` is Forbidden (Boundary Surfaces)

`Any` is **forbidden** in the following contexts, which are **boundary surfaces**:

1. **Function Signatures in Boundary Modules** (within enforcement scope):
   *   Function/method signatures in files defined in `dev/boundary_types_scope.json`
   *   Protocol definitions for cross-layer interfaces
   *   Example: `ICanonicalChatCompletionsBackend.chat_completions()` must use typed contracts, not `Any`

2. **Boundary-Carried Contract-Shaped Payloads**:
   *   Data structures that cross layer boundaries
   *   Request/response payloads exchanged between Transport, Core, and Connectors
   *   Example: `ConnectorChatCompletionsRequest` must use typed contracts, not `dict[str, Any]`

3. **Extension Containers**:
   *   Extension fields must use `JsonValue`, not `Any`
   *   Example: `RequestContext.extensions: dict[str, JsonValue]` ✅, not `dict[str, Any]` ❌

4. **Connector-Facing Contracts**:
   *   All connector API contracts must use canonical typed contracts
   *   Example: Connectors receive `ConnectorChatCompletionsRequest`, not `dict[str, Any]`

5. **Transport Adapter Protocols**:
   *   Adapter protocols that convert between transport and core layers
   *   Example: `IStreamingContentConverter` must use `ProcessedResponse`, not `Any`

**Key Principle**: If code crosses a layer boundary, it must use canonical typed contracts or `JsonValue` for extensions.

### Allowlist Management Workflow

When a boundary violation is strictly necessary, it must be documented via a time-bounded allowlist entry.

#### When to Add an Allowlist Entry

Add an allowlist entry **only** when:

1. **Legacy Compatibility**: Temporary support for legacy interfaces during migration
2. **Time-Bounded Exception**: Known violation with a clear plan to fix within the expiration period
3. **Internal Processing Boundary**: Violation occurs at an internal processing boundary (not cross-layer contract exchange)

**Do NOT** add allowlist entries for:
*   New code introducing violations (should use canonical contracts from the start)
*   Violations without a documented promotion path or fix plan
*   Violations that can be fixed immediately with minimal effort

#### How to Add an Allowlist Entry

Create an entry in `dev/boundary_types_allowlist.json` with the following structure:

```json
{
  "file": "src/connectors/base.py",
  "symbol": "chat_completions",
  "violation": "dict[str, Any]",
  "reason": "Legacy connector API compatibility. Will be hardened in Phase 1 with canonical connector API.",
  "expires_at": "2026-06-30T00:00:00Z",
  "tracking": "typed-contracts-boundary-hardening Phase 1"
}
```

**Required Fields**:
*   **`file`**: Exact file path (relative to project root)
*   **`symbol`**: Optional function/class name (if applicable, `null` if file-wide)
*   **`violation`**: Violation type (`Any-in-signature` or `dict[str, Any]`)
*   **`reason`**: Clear rationale explaining why the violation is necessary
*   **`expires_at`**: RFC3339 timestamp (typically 6-12 months in the future)
*   **`tracking`**: Issue/spec reference (e.g., "typed-contracts-boundary-hardening Phase 1")

**Important**: Every allowlist entry **must** have a documented promotion path or fix plan. The `reason` field should explain how the violation will be resolved.

#### When to Remove an Allowlist Entry

Remove an allowlist entry when:

1. **Violation is Fixed**: The code has been updated to use canonical contracts
2. **Promotion Path Completed**: The violation has been promoted to a typed field or approved extension mechanism
3. **Entry Expires**: Expired entries cause check failures and must be either renewed or the violation fixed

#### Expiration Handling

**Before Expiration**:
*   Review the allowlist entry and assess progress on the promotion path
*   Either fix the violation or renew the entry with:
    *   Updated rationale (if circumstances changed)
    *   New expiration date (typically 6-12 months)
    *   Updated tracking reference (if issue/spec changed)

**After Expiration**:
*   Expired entries cause the boundary type check to fail
*   The violation **must** be fixed; expired entries cannot be renewed without addressing the underlying issue
*   Update the code to use canonical contracts or remove the violation

### Examples

**Permitted `Any` Usage** (Internal-Only):
```python
# Internal middleware processing raw provider responses
class ResponseProcessor:
    def process(self, raw_response: Any) -> ProcessedResponse:  # ✅ Internal processing
        # Normalize raw provider response to ProcessedResponse
        ...

# Serialization method for JSON compatibility
class UsageSummary:
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageSummary:  # ✅ JSON parsing
        ...
```

**Forbidden `Any` Usage** (Boundary Surface):
```python
# FORBIDDEN: Connector API accepting dict[str, Any]
async def chat_completions(
    self,
    request: dict[str, Any]  # ❌ Forbidden at boundary
) -> ResponseEnvelope:
    ...

# CORRECT: Use canonical contract
async def chat_completions(
    self,
    request: ConnectorChatCompletionsRequest  # ✅ Typed contract
) -> ResponseEnvelope:
    ...
```

**Allowlisted Violation** (Time-Bounded Exception):
```python
# Legacy connector compatibility (allowlisted)
async def chat_completions(
    self,
    request_data: CanonicalChatRequest,
    **kwargs: Any  # ⚠️ Allowlisted, expires 2026-06-30
) -> ResponseEnvelope:
    # Entry in dev/boundary_types_allowlist.json with expiration
    ...
```

## Connector Boundary (Phase 1)

Connectors must implement the canonical protocol to ensure type safety.

### `ICanonicalChatCompletionsBackend`

New connectors should implement the `ICanonicalChatCompletionsBackend` protocol (duck typing or explicit inheritance):

```python
async def chat_completions(
    self,
    request: ConnectorChatCompletionsRequest,
) -> ResponseEnvelope | StreamingResponseEnvelope:
    ...
```

The `ConnectorChatCompletionsRequest` bundles all necessary inputs:
*   `request`: The canonical `CanonicalChatRequest` (never a dict).
*   `processed_messages`: Typed `Sequence[ChatMessage]`.
*   `options`: A `dict[str, JsonValue]` for provider options (API keys, URLs).

### Connector Options
Do **not** use `**kwargs` for connector options in the canonical API. Instead, pass options via the `options` dictionary in the request object. This ensures all options are JSON-serializable and explicitly tracked.

## Boundary Surfaces

### What is a Boundary Surface?

A **boundary surface** is a cross-layer seam where data is exchanged between different architectural layers:

1. **Transport ↔ Core**: HTTP/FastAPI controllers and adapters exchange data with core services
2. **Core ↔ Connector**: Core orchestration invokes connector backends
3. **Core ↔ Capture/Replay**: Core services interact with wire capture and replay systems

Boundary surfaces are the **only** places where cross-layer data exchange occurs. Internal implementation details within a single layer are not considered boundary surfaces.

### Boundary Surface Enforcement Scope

The project defines an explicit **boundary surface enforcement scope** that determines which files are subject to boundary type checking. This scope is defined in `dev/boundary_types_scope.json` and serves as the **source of truth** for enforcement.

**Scope Configuration Structure**:
*   **`explicit_files`**: List of exact file paths that must be enforced (highest priority)
*   **`include_globs`**: Glob patterns for files to include in enforcement
*   **`exclude_globs`**: Glob patterns for files to exclude from enforcement

**Precedence Rules**:
*   `explicit_files` override `exclude_globs`
*   If a file matches both `include_globs` and `exclude_globs`, it is excluded unless also present in `explicit_files`

**Phase 0 Scope (Current)**:
Phase 0 enforcement uses **signature-first** enforcement focused on the highest-leverage boundary surfaces:
*   Connector boundary API (`src/connectors/base.py`)
*   Response processor interfaces (`src/core/interfaces/response_processor_interface.py`)
*   Transport adapter protocols (`src/core/transport/fastapi/adapters/protocols.py`)
*   Canonical contract carriers (response envelopes, request context, backend target, usage summary, streaming contracts)

**Future Phases**:
*   **Phase 1+**: Expand enforcement to include connector implementations and additional core service interfaces as they become compliant
*   Scope expansion is incremental and controlled to maintain actionable enforcement

**Important**: Phase 0 scope is **enforced**; violations in Phase 0 scope files will cause the boundary type check to fail. Areas outside Phase 0 scope are **advisory** until the scope is expanded in later phases.

## Boundary Enforcement

The project uses a custom boundary type checker to enforce typed contract rules at boundary surfaces.

### Running the Boundary Type Check

**Canonical Command**:
```bash
./.venv/Scripts/python.exe dev/scripts/check_boundary_types.py
```

This command scans all files defined in the boundary surface enforcement scope (`dev/boundary_types_scope.json`) and reports violations.

**What Violations Are Detected**:
*   **`Any` in signature**: Function signatures, method signatures, or Protocol definitions using `Any` or `dict[str, Any]` for boundary-carried data
*   **`dict[str, Any]`**: Explicit usage of `dict[str, Any]` for contract-shaped payloads at boundary surfaces

**Violation Reporting Format**:
Violations are reported in `file:line:column` format with a human-readable message:
```
src/connectors/base.py:45:12: Function signature uses Any for boundary-carried request payload
```

**Exit Codes**:
*   **0**: Codebase is compliant (no violations or all violations are allowlisted and not expired)
*   **Non-zero**: Violations detected that are not allowlisted or allowlist entries have expired

### Scope Configuration (`dev/boundary_types_scope.json`)

The scope configuration file (`dev/boundary_types_scope.json`) defines which files are subject to boundary type enforcement. This file is the **source of truth** for enforcement scope.

**Current Scope (Phase 0)**:
*   **`explicit_files`**: Explicitly pinned files for signature-first enforcement:
    *   `src/connectors/base.py` (connector boundary API)
    *   `src/core/interfaces/response_processor_interface.py` (response processor seam)
    *   `src/core/transport/fastapi/adapters/protocols.py` (adapter protocol signatures)
    *   `src/core/domain/responses.py` (response envelopes)
    *   `src/core/domain/request_context.py` (context contract)
    *   `src/core/domain/backend_target.py` (routing contract)
    *   `src/core/domain/usage_summary.py` (usage contract)
    *   `src/core/domain/streaming/contracts.py` (typed chunk boundary model)
*   **`include_globs`**: `src/connectors/contracts/**/*.py` (connector-facing contracts)
*   **`exclude_globs`**: Empty (no exclusions in Phase 0)

**Future Scope Expansion**:
*   Phase 1+: Add narrowly targeted `include_globs` as areas become compliant
*   Examples: `src/core/interfaces/**/*.py`, `src/core/transport/fastapi/adapters/**/*.py`
*   `src/core/domain/**/*.py` remains excluded by default, except for explicit canonical contract carriers

### Remediation Workflow

When the boundary type check reports a violation, follow this workflow:

1. **Fix the Violation** (Preferred):
   *   Replace `Any` / `dict[str, Any]` with a canonical contract or `JsonValue`
   *   Use canonical contracts from the [Canonical Contract Set](#canonical-contract-set)
   *   Ensure boundary-carried data uses typed contracts

2. **Allowlist the Violation** (Only if Strictly Necessary):
   *   Use allowlist **only** when the violation is required for legacy compatibility or represents a time-bounded exception
   *   Add an entry to `dev/boundary_types_allowlist.json` with:
     *   **`file`**: Exact file path
     *   **`symbol`**: Optional function/class name (if applicable)
     *   **`violation`**: Violation type (`Any-in-signature` or `dict[str, Any]`)
     *   **`reason`**: Clear rationale explaining why the violation is necessary
     *   **`expires_at`**: RFC3339 timestamp (typically 6-12 months in the future)
     *   **`tracking`**: Issue/spec reference (e.g., "typed-contracts-boundary-hardening Phase 1")
   *   **Must** have a documented promotion path to remove the violation

3. **Verify Fix**:
   *   Re-run the boundary type check to confirm the violation is resolved or properly allowlisted
   *   Ensure expired allowlist entries are renewed or violations are fixed

**Important**: Allowlist entries expire. Expired entries cause the boundary type check to fail, requiring either renewal (with updated rationale) or fixing the violation.

### Allowlist Policy

**When Allowlist Entries Are Appropriate**:
*   **Legacy compatibility**: Temporary support for legacy interfaces during migration
*   **Time-bounded exceptions**: Known violations with a clear plan to fix within the expiration period
*   **Internal processing boundaries**: Violations that occur at internal processing boundaries (not cross-layer contract exchange)

**When Allowlist Entries Are NOT Appropriate**:
*   New code introducing violations (should use canonical contracts from the start)
*   Violations without a documented promotion path or fix plan
*   Violations that can be fixed immediately with minimal effort

**Allowlist Entry Structure**:
```json
{
  "file": "src/connectors/base.py",
  "symbol": "chat_completions",
  "violation": "dict[str, Any]",
  "reason": "Legacy connector API compatibility. Will be hardened in Phase 1 with canonical connector API.",
  "expires_at": "2026-06-30T00:00:00Z",
  "tracking": "typed-contracts-boundary-hardening Phase 1"
}
```

**Expiration Handling**:
*   Expired entries cause the boundary type check to fail
*   Before expiration: Either fix the violation or renew the allowlist entry with updated rationale and expiration date
*   After expiration: The violation must be fixed; expired entries cannot be renewed without addressing the underlying issue

### Integration with CI/Verification Workflow

The boundary type check is integrated into the project's **required verification workflow**:

*   **CI Integration**: New violations introduced in pull requests will cause CI to fail unless properly allowlisted
*   **Pre-commit**: Consider running the boundary type check before committing changes to boundary surfaces
*   **Enforcement Status**: Phase 0 scope is **enforced**; violations in Phase 0 scope files will fail verification

**Forbidden Patterns** (will fail boundary type check):
*   Adding `type: ignore` to bypass the checker without a documented reason and allowlist entry
*   Adding new `dict[str, Any]` fields to boundary contracts
*   Passing internal Core objects (like `AppState`) directly to Connectors
*   Using `Any` in boundary function signatures without allowlist entry

## Migration Guide

### Converting a Legacy Connector
1.  Update the `chat_completions` signature to accept `ConnectorChatCompletionsRequest`.
2.  Remove `**kwargs` usage for options; use `request.options` instead.
3.  Ensure `processed_messages` are treated as `ChatMessage` objects, not dicts.
4.  Return `ResponseEnvelope` or `StreamingResponseEnvelope` with `UsageSummary`.

### promoting Extension Keys
If an extension key in `metadata` or `extensions` becomes stable and widely used:
1.  Propose adding it as a typed field to the relevant canonical contract.
2.  Update the conversion logic to populate the typed field.
3.  Deprecate the extension key usage.
