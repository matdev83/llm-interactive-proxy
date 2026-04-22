# Claude Code Compatibility Layer Plan

Here’s the execution-ready checklist, organized by exact files and in strict TDD order.

## Implementation shape
- Add Claude Code support as a new client-family adapter, but do it with a hybrid strategy:
  - normalize deterministic mismatches in-flight
  - use retry steering only for ambiguous/non-lossless cases
- Keep `apply_patch` always in the retry-steering bucket.
- Make interface/test changes first, then implementation.

## Files to change
- `src/connectors/openai_codex/client_families/base.py`
- `src/connectors/openai_codex/client_families/registry.py`
- `src/connectors/openai_codex/client_families/__init__.py`
- `src/connectors/openai_codex/client_families/claude_code_adapter.py` new
- `src/connectors/openai_codex/interfaces.py`
- `src/connectors/openai_codex/contracts.py`
- `src/connectors/openai_codex/compat.py`
- `src/connectors/openai_codex/payload.py`
- `src/connectors/openai_codex/executor.py`

## Tests to add/change first
- `tests/unit/connectors/openai_codex/test_claude_code_adapter.py` new
- `tests/unit/connectors/openai_codex/test_executor_streaming.py`
- `tests/unit/connectors/openai_codex/test_payload.py`
- optionally `tests/integration/test_codex_kilo_compatibility_e2e.py` only if you want a broader end-to-end compatibility regression later

## TDD phase plan

### Phase 1: contract tests first
- Add failing tests that define the new normalization contract before changing interfaces.
- Expected new behavior:
  - compatibility layer can normalize tool calls before incompatibility retry logic runs
  - normalization is no-op for families that do not implement it
  - non-normalizable tool calls still go through existing incompatible-tool retry path

### Phase 1 file targets
- tests first:
  - `tests/unit/connectors/openai_codex/test_executor_streaming.py`
- then interfaces:
  - `src/connectors/openai_codex/interfaces.py:392`
  - `src/connectors/openai_codex/client_families/base.py:27`
  - `src/connectors/openai_codex/client_families/registry.py:43`
  - `src/connectors/openai_codex/compat.py:42`

### Recommended interface change
- Add a new family-adapter hook in `src/connectors/openai_codex/client_families/base.py:27`:
  - `normalize_tool_calls(response_like, context, state) -> object`
- Add corresponding method to `ICompatibilityLayer` in `src/connectors/openai_codex/interfaces.py:392`
- Registry should apply normalization across adapters before incompatibility detection.
- Compatibility layer should expose normalization to executor.

### Why this is the cleanest design
- keeps family-specific logic in adapters
- avoids hardcoding Claude behavior into executor
- supports future families with the same pattern

### Phase 2: Claude adapter unit tests first
Add `tests/unit/connectors/openai_codex/test_claude_code_adapter.py` with red tests for:

- **Detection**
  - detects `claude-code` in `metadata.agent`
  - detects `claude-code` in `User-Agent`
  - detects `@anthropic-ai/claude-code`
  - does not match generic Anthropic traffic

- **Bridge prompt**
  - appends `Claude Code compatibility mode` once
  - bridge mentions `ReadFile`, `Grep`, `Edit`, `Write`, `Bash`, `PowerShell`
  - bridge says to avoid `apply_patch`
  - bridge says to use absolute paths
  - bridge says to avoid `cd`

- **Prompt/input cleanup**
  - removes duplicated Claude tool environment prompt items if present
  - injects one bridge developer message into `input`
  - deduplicates repeated bridge injection

- **Tool support resolution**
  - correctly reads tools from request schema objects and dicts
  - handles exact case-sensitive Claude names while comparing logically case-insensitively where needed

### Phase 3: alias-compatibility tests first
In `tests/unit/connectors/openai_codex/test_claude_code_adapter.py`, add failing tests for:

- `read` and `read_file` compatible with `ReadFile`
- `grep` and `grep_files` compatible with `Grep`
- `bash`, `shell`, `local_shell_call` compatible with `Bash`
- same shell aliases compatible with `PowerShell` when `Bash` absent
- `write` and `create` compatible with `Write`
- `edit` compatible with `Edit`
- `apply_patch` incompatible even when `Edit` exists

This defines the compatibility allowlist before implementation.

### Phase 4: normalization tests first
Still in `tests/unit/connectors/openai_codex/test_claude_code_adapter.py`, add failing tests for deterministic in-flight normalization.

### Normalization cases to support
- **Read**
  - `read(path=...)` -> `ReadFile(file_path=...)`
  - `read_file(file_path=..., offset=..., limit=...)` -> `ReadFile(...)`
- **Grep**
  - `grep(pattern=..., path=..., include=...)` -> `Grep(...)`
  - `grep_files(...)` -> `Grep(...)`
- **Shell**
  - `shell(command="git status")` -> `Bash(command="git status")` or `PowerShell(...)`
  - array-valued `command` becomes a single string only when every element is a string
- **Write**
  - `write(path/file_path, content)` -> `Write(path, content)`
  - `create(path/file_path, content)` -> `Write(path, content)`
- **Edit**
  - `edit(path/file_path, old_string|oldText, new_string|newText)` -> `Edit(...)`

### Normalization cases to explicitly reject
- `apply_patch`
- shell commands with non-string arrays or nested command structures
- grep payloads missing required `pattern`
- edit payloads missing either old/new text
- write payloads missing content or path

Rejected normalizations should remain unchanged so incompatible-tool retry can catch them.

### Phase 5: executor tests first
Extend `tests/unit/connectors/openai_codex/test_executor_streaming.py:973` style coverage with failing tests for Claude-specific flow:

- if tool call is normalizable:
  - no retry
  - stream continues
  - normalized tool name/args are what downstream sees
- if tool call is non-normalizable:
  - stream cancels before visible output
  - retry steering added
- if visible output already emitted:
  - no retry, current chunk passes through
- if only `PowerShell` is exposed:
  - shell alias normalizes to `PowerShell`
- if both `Bash` and `PowerShell` are exposed:
  - choose `PowerShell` in this Windows project

This is where the hybrid strategy becomes enforced by tests.

### Phase 6: payload-builder tests first
Add/extend tests in `tests/unit/connectors/openai_codex/test_payload.py` to confirm:

- Claude adapter is registered in both family registries used by `PayloadBuilder` in `src/connectors/openai_codex/payload.py:80`
- translated payload path gets Claude bridge instructions
- passthrough payload path gets Claude bridge instructions
- non-Claude payloads unchanged
- no duplicate bridge block

### Phase 7: implement contract changes
Only after the above tests are red:

- `src/connectors/openai_codex/client_families/base.py`
  - add `normalize_tool_calls(...)`
- `src/connectors/openai_codex/client_families/registry.py`
  - add `normalize_tool_calls(...)` dispatcher over adapters
- `src/connectors/openai_codex/interfaces.py`
  - extend `ICompatibilityLayer`
- `src/connectors/openai_codex/compat.py`
  - implement compatibility-layer normalization delegating to registry
- `src/connectors/openai_codex/executor.py`
  - call normalization before `_detect_incompatible_tool_calls(...)`

### Recommended executor call order
- normalize chunk/content via existing `_normalize_processed_stream_chunk(...)`
- run compatibility-layer tool normalization on normalized content
- then extract tool calls
- then detect incompatibilities
- then retry if needed

That keeps Claude normalization after raw response normalization but before retry logic.

### Phase 8: implement Claude adapter
Create `src/connectors/openai_codex/client_families/claude_code_adapter.py` with:

- request detection
- bridge prompt
- tool alias map
- supported-tool resolver
- `normalize_tool_calls(...)`
- `detect_incompatible_tool_calls(...)`
- `append_incompatible_tool_steering(...)`
- payload input cleanup and bridge insertion

Register it in:
- `src/connectors/openai_codex/client_families/__init__.py`
- `src/connectors/openai_codex/compat.py:79`
- `src/connectors/openai_codex/payload.py:80`

### Suggested adapter internals
- constants:
  - `_CLAUDE_BRIDGE_MARKER`
  - `_CLAUDE_INCOMPATIBLE_MARKER`
  - `_CLAUDE_USER_AGENT_MARKERS`
  - `_CLAUDE_TOOL_EQUIVALENTS`
- helpers:
  - `_is_claude_code_request(...)`
  - `_resolve_supported_tool_names(...)`
  - `_normalize_tool_call_dict(...)`
  - `_choose_shell_target(...)`
  - `_can_losslessly_join_shell_command(...)`
  - `_build_bridge_prompt(...)`
  - `_build_incompatible_tool_steering(...)`

### Phase 9: implementation rules for normalizers
- **ReadFile**
  - output keys: `file_path`, optional `offset`, `limit`
- **Grep**
  - output keys should match the actual Claude client’s exposed schema as closely as possible; if repo/user tooling expects a different key than prompt docs imply, use the real session schema
- **Bash/PowerShell**
  - output `command` as string
  - preserve `description` when present
  - preserve `timeout` if compatible
- **Write**
  - output `path` plus `content` if that is what the real session schema uses; otherwise adapt to actual exposed parameter names
- **Edit**
  - output parameter names matching the real exposed schema for Claude client session
  - important: because exact parameter names may vary from snapshot wording vs actual bridged tool schema, implementation should derive from exposed tool definitions when practical, not only from hardcoded docs

That last point is important: tool-name normalization can be hardcoded, but parameter naming should prefer the actual request tool schema if available.

### Phase 10: retry steering implementation
Use retry steering only when normalization fails or tool truly unsupported.

Steering should say:
- do not call these incompatible tools again
- this session uses Claude Code tools
- available tools are ...
- use:
  - `ReadFile` for file inspection
  - `Grep` for content search
  - `Bash`/`PowerShell` for terminal commands
  - `Edit` for exact replacements
  - `Write` for full rewrites
- `apply_patch` is unavailable here
- use absolute paths
- avoid `cd`

### Phase 11: regression run order
After implementation:
- run Claude adapter unit tests first
- run executor streaming tests second
- run payload tests third
- then run family regression tests:
  - `tests/unit/connectors/openai_codex/test_pi_adapter.py`
  - `tests/unit/connectors/openai_codex/test_droid_adapter.py`
  - relevant OpenCode payload tests in `tests/unit/connectors/openai_codex/test_payload.py`

## Recommended acceptance checklist
- Claude Code request detection works
- bridge instructions appear once
- deterministic tool mismatches normalize in-flight
- non-deterministic mismatches retry with steering
- `apply_patch` never treated as compatible
- shell aliases choose `PowerShell` when appropriate
- executor retries only before visible output
- OpenCode, Pi, and Droid regressions remain green

## One targeted question
My recommended default is: prefer deriving Claude parameter names from the actual exposed tool schema in `context.request.tools` when possible, and use hardcoded fallback names only when schema details are incomplete. That is safer than hardcoding snapshot assumptions. Do you want the eventual implementation to follow that schema-driven approach, or should it use a fixed hardcoded Claude parameter contract from the prompt snapshots?
