# Codex Compatibility Specification

## Overview
The OpenAI Codex backend bundled with this proxy expects the canonical `gpt_5_codex_prompt.md` system instructions and a small set of native tools. Real clients such as KiloCode deliver rich personas, tool metadata, and XML-style tool invocations that the Codex backend does not natively understand. Attempts to forward Kilo’s system prompt or tool schema directly result in Codex rejecting the request (`HTTP 400: Instructions are not valid`) or ignoring the requested tool actions.

## Activation Conditions
This compatibility layer must remain **agent-specific** to avoid unnecessary overhead and unintended rewrites. It activates only when:
- The selected backend is `openai-codex`.
- The client/agent is confidently identified as **KiloCode**.

### Detection Strategy
1. **Explicit Metadata** – Prefer structured hints provided by the proxy pipeline (e.g., `request.agent`, session metadata). If the agent string matches `kilocode` (case-insensitive) or known aliases (`Kilo-Code`, `KiloCode/`, etc.), enabling is safe.
2. **HTTP Headers** – Fall back to inspecting incoming headers (`User-Agent: Kilo-Code/…`). Cache the result per session to avoid repeated string comparisons.
3. **Payload Heuristics (tertiary fallback)** – Detect Kilo-specific XML tags (`<attempt_completion>`, `<use_mcp_tool>`) only if neither metadata nor headers are available. This heuristic should only trigger once per session, after which the session is tagged as Kilo-compatible.
4. **Session Cache** – Store the detection result in the request-processing context so subsequent requests reuse the decision until the session switches agent or backend. Clearing/invalidating should occur when the agent or backend changes.

If any check fails, the translation layer stays dormant, preserving default Codex behaviour and avoiding extra processing.

## Current State
- **Working**
  - Codex backend loads OAuth credentials, refreshes tokens, and can stream responses when the canonical instructions are preserved.
  - `<user_instructions>` injection works; client-provided guidance can be appended safely as a user-level block.
  - The proxy ships Codex’s default tools (`shell`, custom `apply_patch`, `view_image`).
  - Wire-captured scenarios confirm Codex responds successfully once the canonical prompt is respected.

- **Recent Observations**
  - The Codex service hard-rejects any alteration to its canonical system prompt and returns `HTTP 400` with no body. The rejection occurs even if we only prepend persona text before the canonical block.
  - Sanitising instructions to ASCII is necessary but insufficient; the canonical prompt must remain byte-for-byte identical to the one issued by `codex-cli`.
  - Client-provided system prompts can be appended only as user-level instructions. Attempts to mix personas (e.g., merging Codex and KiloCode personas) trigger the same 400 rejection.
  - Universal “execute any tool” passthroughs proved fragile and caused broad regressions because they bypassed Codex-specific invariants.

- **Not Working / Gaps**
  - Codex rejects any modification of its system prompt or appended instructions. Even trimming only persona lines triggers `Instructions are not valid`.
  - KiloCode emits XML tags (`<read_file>`, `<use_mcp_tool>`, `<attempt_completion>`, etc.) that Codex cannot parse; current translation layer only understands a subset (`execute_command`, `apply_diff`, `view_image`).
  - Tool surfaces do not align; Kilo expects >20 tools, Codex exposes only a handful by default. There is no automatic mapping from Kilo tool invocations to Codex tool handlers.
  - MCP usage: Kilo’s `use_mcp_tool` and `access_mcp_resource` require bridging to Codex’s MCP handlers.
  - Streaming retries, evaluator logic, and approval flows are wired for Codex CLI semantics, not Kilo’s.

## Goal
Introduce a translation layer inside the proxy that:
1. Keeps Codex’s canonical `instructions` untouched.
2. Converts client system prompts / settings into `<user_instructions>` blocks.
3. Maps client tool invocations (especially Kilo’s XML payloads) into Codex-compatible tool calls or executes them on behalf of Codex, returning results in a format clients expect.
4. Optionally exposes Codex tool metadata back to clients that speak OpenAI/Anthropic/Gemini schemas.
5. Activates **only** when detection logic confirms `openai-codex` + KiloCode; otherwise no additional processing occurs.

## Tool Mapping (Codex ↔ Kilo)
| Codex Tool | Purpose | Closest Kilo Tool(s) | Compatibility Notes |
| - | - | - | - |
| `shell` (`container.exec`, `local_shell`) | Run commands | `execute_command` | Needs argument coercion (array vs string). |
| `unified_exec` (feature) | PTY session reuse | `execute_command` | Kilo lacks session reuse; adapt or disable. |
| `apply_patch` (freeform grammar) | Diff patch | `use_mcp_tool → patch_file`, `search_and_replace`, `edit_file`, `write_to_file` | Requires translation to MCP or synthesized edits. |
| `view_image` | Attach image | *(none)* | Optional enhancement. |
| `list_mcp_resources` | Enumerate MCP resources | *(none)* | Could expose as helper. |
| `list_mcp_resource_templates` | Enumerate templates | *(none)* | Same. |
| `read_mcp_resource` | Read MCP resource | `access_mcp_resource` | Parameter rename only. |
| `update_plan` | Task planning | `new_task`, `switch_mode`, `attempt_completion` | Semantics differ; bridging optional. |
| `web_search` | Web search | `browser_action` | Needs custom shim. |
| `grep_files` (experimental) | Regex search | `codebase_search`, `search_files` | Map arguments and responses. |
| `read_file` (experimental) | Read file ranges | `read_file` | Map `file_path`/offset fields. |
| `list_dir` (experimental) | Directory listing | `list_files` | Map `dir_path`/depth to Kilo schema. |
| `test_sync_tool` | Test sync barrier | *(none)* | Can omit. |
| `exec_command` / `write_stdin` | Streaming shell | `execute_command` | Expose only if streaming is implemented. |
| Dynamic MCP tools | Custom MCP actions | `use_mcp_tool` | Translate names/args to Kilo MCP wrapper. |

Kilo Tool Inventory (from `src/shared/tools.ts`):
`execute_command`, `read_file`, `fetch_instructions`, `write_to_file`, `insert_content`, `codebase_search`, `search_files`, `list_files`, `list_code_definition_names`, `browser_action`, `use_mcp_tool`, `access_mcp_resource`, `ask_followup_question`, `attempt_completion`, `switch_mode`, `new_task`, `report_bug`, `run_slash_command`, `search_and_replace`, `edit_file`, `generate_image`.

## Translation Strategy
0. **Conditional Activation**
   - Implement a lightweight detector (metadata/header/heuristic) that tags a session as “Codex-Kilo compatible.”
   - Store detection state alongside session context to reuse across requests until backend or agent changes.

1. **Prompt Handling**
   - Always send canonical Codex instructions in `instructions` field.
   - Collect client personas / rules, sanitize to ASCII, inject as first input item `<user_instructions>`.

2. **Tool Registry Adapter**
   - Extend `openai_codex` connector to advertise synthetic OpenAI tools that mirror Kilo’s high-frequency operations (read/list/search/patch) but internally call Codex shell or proxy services.
   - Add schema coercion: convert Kilo tool arguments into the JSON schemas Codex expects, preserving validations.

3. **Invocation Translator**
   - Extend `_openai_codex_request_translator` + `tool_call_text_parser` to parse Kilo XML blocks, convert them into structured requests (e.g. map `<read_file>` to `read_file` tool, `<use_mcp_tool>` to `apply_patch` or direct MCP call).
   - For unmatched tags (e.g. `attempt_completion`), implement direct proxy-side behavior (status updates, logging) or instruct clients to ignore them.

4. **Execution Layer**
   - Implement adapters that carry out Kilo’s requested operations: file IO, search, patch application, MCP bridging.
   - Ensure responses are converted back into the textual formats Kilo expects (`[read_file] Result: …`, `<result>`, etc.).

5. **Compatibility Testing**
   - Use wire-captured sessions to build regression tests verifying translation fidelity.
   - Validate each tool path with unit tests and optional integration tests using mock FS/MCP services.

6. **Progressive Rollout**
   - Start with high-frequency, low-complexity tools (read/list/execute) to unblock basic workflows.
   - Gradually add editor-focused tools (`search_and_replace`, `edit_file`) and MCP bridging.
   - Document unsupported tools and provide fallbacks or explicit errors.

## Risks & Considerations
- Mis-identifying agents could apply translations inappropriately; maintain conservative detection logic and allow opt-out.
- Maintaining parity with evolving Kilo tool definitions will require continuous updates.
- MCP integration is non-trivial; we must ensure sandbox/approval policies align (especially for `patch_file`).
- Performance: introducing translation/execution layers will add latency; caching or streaming optimizations may be necessary.
- Error reporting: mismatched schemas should raise explicit errors with actionable guidance so users understand why a tool failed.

## Acceptance Criteria
- Canonical Codex system instructions remain untouched for all translated requests; client personas appear only in user-level blocks.
- Compatibility layer activates exclusively when `backend=openai-codex` **and** session metadata positively identifies KiloCode (or documented aliases).
- High-frequency Kilo tools (`execute_command`, `read_file`, `list_files`, `codebase_search`, `attempt_completion`, `ask_followup_question`) are either translated into Codex-compatible tool calls or handled proxy-side with round-trip tests demonstrating fidelity.
- Translation failures surface actionable error messages (no silent fallbacks to Codex with unsupported XML left in place).
- Automated tests cover detection (positive/negative), prompt translation, and tool round-trips without requiring access to the live Codex service.
- Documentation (this spec + plan) is updated whenever new tools are mapped or limitations identified.

## Anti-Patterns to Avoid
- **Universal Tool Passthroughs** – Avoid injecting blanket handlers that attempt to execute arbitrary Kilo tools via a generic executor; this bypass leads to missing context, violates Codex invariants, and reintroduces the regressions we observed.
- **Unauthenticated Activation** – Do not trigger the translation layer solely on heuristic XML detection without session caching; ensure the backend+agent pair is verified to prevent affecting unrelated clients.
- **Prompt Mutation** – Never mutate or reconstruct Codex’s canonical instructions; even well-intentioned whitespace changes cause hard failures.
- **Tool Flooding** – Avoid advertising unsupported Kilo tools to Codex clients before translation logic exists; premature exposure leads to confusing 400/422 errors.
- **Silent Error Suppression** – Do not swallow translation errors and continue; always raise a specific compatibility exception so operators can diagnose issues quickly.
