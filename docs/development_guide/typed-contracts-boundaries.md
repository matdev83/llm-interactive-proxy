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

### Approved Extension Mechanisms

When you need to pass provider-specific or protocol-specific data across a boundary, use one of the **approved extension containers**. Do *not* add new top-level `Any` fields.

*   **`RequestContext.extensions: dict[str, JsonValue]`**: For cross-layer context metadata.
*   **`ConnectorRequestContext.extensions: dict[str, JsonValue]`**: For connector-facing context.
*   **`UsageSummary.extensions: dict[str, JsonValue]`**: For provider-specific usage data.
*   **`ResponseEnvelope.metadata: dict[str, JsonValue]`**: For response metadata.
*   **`ProcessedResponse.metadata: dict[str, JsonValue]`**: For streaming chunk metadata.

**Note:** All extension values must be `JsonValue` (JSON-serializable). This ensures deterministic logging, wire capture, and replay.

### Legacy Mechanisms (Deprecated/Restricted)

The following mechanisms exist for backward compatibility but should not be used for new features:
*   `ChatRequest.extra_body`: Allowed for protocol compatibility, but prefer typed fields where possible.
*   `ToolCall.extra_content`: Allowed for provider-specific tool artifacts.
*   `StreamingChunk.payload.opaque_json_dict`: Allowed as an escape hatch for non-standard streaming payloads.

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

## Boundary Enforcement

The project uses a custom boundary type checker to enforce these rules.

### Running the Check

```bash
./.venv/Scripts/python.exe dev/scripts/check_boundary_types.py
```

This script scans files defined in `dev/boundary_types_scope.json` and reports:
*   **`Any` in signature**: Function signatures using `Any` or `dict[str, Any]`.
*   **`dict[str, Any]`**: explicit usage of raw dicts in contracts.

### Scope Configuration (`dev/boundary_types_scope.json`)

The scope defines which files are enforced.
*   **Phase 0/1**: Explicitly pinned files (interfaces, protocols, base connector, contract definitions).
*   **Future**: Will expand to include all connector implementations and core services.

### Handling Violations

If you encounter a violation:
1.  **Fix it**: Replace `Any` / `dict` with a canonical contract or `JsonValue`.
2.  **Allowlist it**: If strictly necessary (e.g., legacy compatibility), add an entry to `dev/boundary_types_allowlist.json`.
    *   **Must** include an expiration date (`expires_at`).
    *   **Must** include a tracking reference (`tracking`).
    *   **Must** have a clear rationale.

**Forbidden Patterns:**
*   Adding `type: ignore` to bypass the checker without a documented reason.
*   Adding new `dict[str, Any]` fields to boundary contracts.
*   Passing internal Core objects (like `AppState`) directly to Connectors.

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
