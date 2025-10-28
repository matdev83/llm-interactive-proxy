# Codex–Kilo Compatibility Implementation Plan

## Phase 0 – Conditional Activation
1. **Detection Hooks**
   - Implement light-weight detection that marks a session as “Codex–Kilo compatible” only when backend=`openai-codex` and the agent metadata / headers imply KiloCode.
   - Preferred order: explicit `request.agent` → HTTP `User-Agent` → payload heuristic (XML tags). Document exact string patterns and thresholds.
2. **Session State Cache**
   - Store detection outcome in session/context so subsequent requests reuse the decision without re-evaluating heuristics.
   - Invalidate cache when backend or agent changes (or session resets).
3. **Feature Flag / Toggle**
   - Guard the translation layer behind a configuration flag to enable gradual rollout and allow operators to disable behaviour quickly.
4. **Unit Tests**
   - Add coverage for detection logic (positive/negative cases, caching behaviour).

## Phase 1 – Foundations & Prompt Handling
1. **Repository Prep**
   - Ensure spec alignment (this document + `spec.md`).
   - Add unit-test harness for Codex request translation (mock connector + fake Codex responses).
2. **Instruction Normalization**
   - Implement helper that extracts client personas/settings and injects them into `<user_instructions>` (already partially done; extend tests).
   - Add regression tests verifying Codex accepts payloads with the new blocks.
3. **Telemetry & Debugging**
   - Instrument logging for translated tool calls (before/after schemas) to aid later phases.

## Phase 2 – Core Tool Translation
Focus on operations that appear in nearly every Kilo session: reading files, listing directories, running commands, finalising turns.

1. **`read_file` Translation**
   - Extend `tool_call_text_parser` to parse `<read_file>` XML (path, optional args).
   - Map to Codex `read_file` tool if available; otherwise execute via proxy FS reader and return `[read_file] Result:` block.
   - Unit tests: XML→request struct, FS mocks, round-trip response.

2. **`list_files` / Directory Listing**
   - Parse `<list_files>` tag (`path`, `recursive`).
   - Map to Codex `list_dir` tool or implement proxy-side directory walker.
   - Return textual result matching Kilo format.

3. **`execute_command`**
   - Support `<execute_command>` (legacy) and Codex `shell` tool with precise command array conversion.
   - Handle `cwd`, `timeout`, `with_escalated_permissions` mapping.
   - Implement streaming output aggregation if necessary.

4. **`attempt_completion` and `ask_followup_question`**
   - Ensure these control tags don’t reach Codex; handle inside proxy (update session state, log completion).

5. **Testing**
   - Create high-level fixtures simulating Kilo conversation (read→edit→completion) to verify Phase 2 coverage.

## Phase 3 – Editing & Patch Workflow
1. **`use_mcp_tool` (patch-file)**
   - Detect `patch_file` invocation, convert diff payload to Codex `apply_patch` grammar where possible.
   - If grammar conversion is infeasible, call MCP server directly (requires MCP client integration) and synthesize Codex-style acknowledgement.

2. **`search_and_replace`, `write_to_file`, `insert_content`, `edit_file`**
   - Implement composite operations using existing FS helpers or new service layer (Morph-like editing if available).
   - Ensure output matches `[tool] Result:` conventions Kilo expects.

3. **`codebase_search` / `search_files`**
   - Map to Codex `grep_files` or proxy search API; convert parameters (`pattern`, `include`, `recursive`).

4. **Regression suite**: extended scenarios covering patch apply and follow-up read/verification.

## Phase 4 – MCP Bridging & Advanced Tools
1. **MCP Resource Access**
   - Map `access_mcp_resource` to Codex `read_mcp_resource` (parameter rename).
   - Implement `list_mcp_resources` fallback if Kilo requests it.

2. **Generic `use_mcp_tool`**
   - Build dispatcher that forwards arbitrary MCP tool calls to configured servers, translating schema to Codex expectations when possible.

3. **Browser / Web Search Features**
   - Decide on feasibility of mapping `browser_action` to Codex `web_search` or provide stub responses.

4. **Mode / Task Controls**
   - Clarify how `switch_mode`, `new_task`, `report_bug`, `generate_image` should behave when routed through Codex (likely proxy-managed, no Codex interaction).

## Phase 5 – Hardening & Rollout
1. **Error Handling**
   - Standardize exception hierarchy and convert to client-friendly errors (with actionable messages when a tool is unsupported).

2. **Performance Profiling**
   - Measure added latency; cache read results where appropriate (while respecting consistency).

3. **Documentation & Operator Guides**
   - Update user docs with compatibility details, known limitations, and configuration flags for translation layer.

4. **Staged Rollout**
   - Enable translation layer behind feature flag, test with pilot workloads, then promote to default.

