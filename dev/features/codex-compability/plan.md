# Codex–Kilo Compatibility Implementation Plan

## Lessons Learned
- Codex refuses any change to its canonical instructions; translation must preserve the original prompt verbatim and surface client personas elsewhere.
- Broad universal tool executors caused regressions because they bypassed Codex-aware behaviour and leaked into non-Kilo sessions.
- The compatibility layer must be opt-in per session, with explicit detection and caching to avoid repeated string heuristics or accidental activation.
- Tests should simulate end-to-end XML translations without contacting the live Codex service; reliance on ad-hoc integration tests made earlier efforts brittle.

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

**Acceptance Criteria**
- Session metadata or headers trigger activation only when they match the curated Kilo alias list.
- Negative tests prove that non-Kilo agents (Cursor, Cline, etc.) never activate the layer.
- Detection results are cached per session and cleared when backend or agent switches.
- Feature flag allows disabling the entire layer without code changes.

## Phase 1 – Foundations & Prompt Handling
1. **Repository Prep**
   - Ensure spec alignment (this document + `spec.md`).
   - Add unit-test harness for Codex request translation (mock connector + fake Codex responses).
2. **Instruction Normalization**
   - Implement helper that extracts client personas/settings and injects them into `<user_instructions>` (already partially done; extend tests).
   - Add regression tests verifying Codex accepts payloads with the new blocks.
3. **Telemetry & Debugging**
   - Instrument logging for translated tool calls (before/after schemas) to aid later phases.

**Acceptance Criteria**
- Canonical system prompt sent to Codex matches the CLI reference byte-for-byte (snapshot test).
- Client personas appear only in user-level payloads, validated via unit tests.
- Logging includes agent detection state, applied mappings, and rejection reasons.
- Harness allows future phases to add translation tests without hitting the network.

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

**Acceptance Criteria**
- Unit tests cover XML parsing and translation for each tool listed above.
- Mocked execution returns responses formatted exactly like Kilo expects (verified via golden files or snapshot tests).
- Negative tests confirm unsupported tags raise descriptive compatibility errors.
- Manual verification demonstrates Codex accepts the translated payload (no 400 rejections).

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

**Acceptance Criteria**
- Diff-style edits either use Codex `apply_patch` or an audited proxy alternative with consistent output.
- Editing commands include conflict handling and produce deterministic responses (snapshots).
- Search tools honour include/exclude semantics with tests covering glob and regex inputs.
- Regression suite exercises read/edit cycles without leaking untranslated XML.

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

**Acceptance Criteria**
- MCP bridge passes integration tests using local mock servers.
- Unsupported browser/mode tools emit explicit guidance rather than silent failures.
- Telemetry records the origin MCP tool name and resulting action to support debugging.

## Phase 5 – Hardening & Rollout
1. **Error Handling**
   - Standardize exception hierarchy and convert to client-friendly errors (with actionable messages when a tool is unsupported).

2. **Performance Profiling**
   - Measure added latency; cache read results where appropriate (while respecting consistency).

3. **Documentation & Operator Guides**
   - Update user docs with compatibility details, known limitations, and configuration flags for translation layer.

4. **Staged Rollout**
   - Enable translation layer behind feature flag, test with pilot workloads, then promote to default.

**Acceptance Criteria**
- Error responses trace back to specific translation steps (prompt, detection, tool mapping) with unique error codes.
- Profiling demonstrates that added latency stays within agreed thresholds (document target budgets).
- Documentation explains enabling/disabling the layer, supported tools, and fallback behaviour.
- Rollout checklist completed (feature flag defaults, monitoring dashboards, runbook).

## Anti-Patterns to Avoid
- Swapping in “universal” executors that bypass Codex-specific invariants or add tools indiscriminately.
- Relying solely on heuristics without session caching; this risks repeated expensive detections and false positives.
- Advertising Kilo tool schemas before the matching translation path exists.
- Mutating Codex instructions, including whitespace, casing, or extra headers.
- Suppressing translation errors or returning partially processed XML to the client; always fail fast with diagnostics.
