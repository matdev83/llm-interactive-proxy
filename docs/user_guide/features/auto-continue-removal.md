# Auto Continue/Proceed Removal

Automatically detect and exclude mechanical "continue" / "proceed" user messages from backend submissions after connectivity interruptions, keeping context windows clean.

## Overview

When a coding agent session is interrupted (network drop, timeout, etc.), users commonly type `continue` or `proceed` to resume. These messages serve a purely mechanical purpose of re-enabling the agent loop and provide no semantic value to the remote LLM. Without this feature, they pollute the context window and are sent to every backend on every subsequent turn.

The Auto Continue/Proceed Removal feature detects when the very last user message is exactly `continue` or `proceed` (trimmed, case-insensitive) and tags it as non-forwardable. The existing non-forwardable enforcement layer then silently excludes it from outbound payloads to remote LLMs. The message remains in the agent's local context history so the coding agent continues building a complete window; only the transmission to the remote model is affected.

## Key Features

- **Exact match only**: Only pure `continue` or `proceed` strings are matched (case-insensitive, trimmed). Phrases like `please continue` or `continue working` are **not** affected.
- **Last-message scope**: Only the final user message in the request is checked. Earlier occurrences are left untouched.
- **Non-forwardable tagging**: Uses the existing `NEVER_FORWARD` mechanism so the proxy keeps the message in local history but excludes it from all backend transmissions.
- **Default enabled**: Active by default; disable explicitly when needed.
- **Fail-open**: If the non-forwardable registry or identity service is unavailable, the feature degrades gracefully without breaking requests.

## How It Works

1. During the request transform pipeline, the proxy inspects the last message.
2. If the message role is `user` and its content (trimmed, lowercased) is exactly `continue` or `proceed`, the proxy computes a deterministic identity and tags it with `NEVER_FORWARD` and reason `auto_continue_removal`.
3. Later, just before the backend call, the non-forwardable message enforcer filters out tagged messages from the outbound payload.
4. On subsequent turns the coding agent resubmits the same context window; the tag persists for the session lifetime, so the message continues to be excluded.

## Configuration

The feature is **enabled by default**. Configuration follows precedence: CLI > Environment > Config File.

### CLI Flag

```bash
# Disable the feature
python -m src.core.cli --disable-auto-continue-removal
```

### Environment Variable

```bash
# Disable the feature
export AUTO_CONTINUE_REMOVAL_ENABLED=false
```

### Config File

```yaml
# config.yaml
session:
  auto_continue_removal_enabled: false
```

## When to Disable

- You want the remote LLM to see literal `continue` / `proceed` prompts (e.g. for debugging agent behavior).
- Your workflow uses custom continue-like keywords that should reach the model.
- You are testing context window behavior and need every message forwarded verbatim.

## Logging

When a message is tagged, the proxy logs at INFO level:

```
Auto continue removal: tagged last user message for session abc-123, reason=auto_continue_removal
```

Debug-level logging shows when messages are checked but not matched.

## Related Features

- [Non-Forwardable Message Tagging](../features/non-forwardable-message-tagging.md) - Underlying tagging and enforcement mechanism
- [Quality Verifier System](quality-verifier.md) - Verifies individual responses for quality
- [Context Window Enforcement](context-window-enforcement.md) - Enforces per-model context limits
