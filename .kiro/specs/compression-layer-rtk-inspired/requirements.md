# Requirements Document

## Project Description (Input)

Scope of this spec is to implement proxy improvements related to **dynamic compression** to reduce token usage.

We already have related compression/compaction functionality, but it must be better generalized/organized to support:
- A broader set of applications and supported tools
- Multiple compression methods (inspired by RTK)
- Feature-flag gating so users can opt in/out of specific behaviors if they disrupt workflows

Reference implementation to replicate key features from: `rtk-ai/rtk` (RTK - Rust Token Killer).
Cloned RTK repo code is available for inspection in the following directory: `./dev/thrdparty/rtk/`

## Introduction

This spec defines requirements for a **feature-flagged, dynamic output-compression system** inside **LLM Interactive Proxy** that reduces token usage while preserving correctness, debuggability, and workflow compatibility.

**Brownfield context**: The codebase already contains three compression-adjacent mechanisms (stale history compaction, pytest-result compression, Gemini-specific tool-output truncation). These are fragmented and not generalized. This spec targets progressive unification under a strategy-based compression subsystem while preserving existing behavior as compatibility contracts.

**Reference implementation**: Key compression techniques are modeled after `rtk-ai/rtk` (RTK), adapted for the proxy's async, DI-managed, multi-backend architecture. Shell-hook and terminal-integration patterns from RTK do not transfer (the proxy operates at the API layer).

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM clients/agents via unified API
- Operators managing configuration, safety controls, and observability
- End-users relying on stable tool/command workflows through agents

## Technical Constraints (Project Guardrails)

- Async compatibility: Must use `async/await` patterns; no blocking I/O in async paths
- DI integration: Services registered via `ServiceCollection`; collaborators depend on interfaces from `src/core/interfaces/`
- Error hierarchy: Exceptions extend `LLMProxyError`; transport layer maps to HTTP responses
- Config precedence: CLI > ENV > YAML > defaults
- Staged initialization: New compression services must be wirable through `src/core/app/stages/` without ad-hoc startup hooks
- Pipeline placement: Dynamic compression operates on tool outputs during backend request preparation, before backend translation

## Requirements

### Requirement 1: Feature-flagged compression controls

**Objective:** As an operator, I want to enable/disable compression globally and per feature, so that I can safely roll out compression and opt out of disruptive behaviors.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. The LLM Interactive Proxy shall provide a global switch to enable or disable the dynamic compression system.
2. Where no explicit configuration enabling compression is provided, the LLM Interactive Proxy shall default to dynamic compression disabled.
3. Where a compression feature flag is disabled, the LLM Interactive Proxy shall bypass that feature and shall not alter the corresponding output.
4. The LLM Interactive Proxy shall allow enabling or disabling compression per tool category and per compression method independently.
5. If compression configuration is invalid or references unknown flags, the LLM Interactive Proxy shall fail open by bypassing compression and shall surface an operator-visible warning.
6. When compression configuration changes are applied, the LLM Interactive Proxy shall apply the updated settings to subsequent requests deterministically.

#### Technical Constraints

- Config precedence: CLI > ENV > YAML > defaults

### Requirement 2: Dynamic selection of compression behavior

**Objective:** As a developer, I want the proxy to select appropriate compression dynamically based on output characteristics, so that the system reduces tokens without requiring client changes.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. When the LLM Interactive Proxy processes a tool output eligible for compression, it shall select compression behavior based on configured rules and observable output metadata (for example: tool name/category, content type, size).
2. When multiple compression methods match an output, the LLM Interactive Proxy shall apply them in a deterministic, configurable priority order.
3. If no compression method matches an eligible output, the LLM Interactive Proxy shall pass the output through unchanged.
4. Where a compression level (for example: conservative/balanced/aggressive) is configured, the LLM Interactive Proxy shall apply the configured level consistently for matching outputs.
5. When a request is at risk of exceeding the configured context/token budget and dynamic compression is enabled, the LLM Interactive Proxy shall increase compression aggressiveness within operator-configured limits before failing the request for size alone.
6. The LLM Interactive Proxy shall only apply dynamic compression to outputs that exceed a configurable minimum size threshold, and shall pass smaller outputs through unchanged.

#### Technical Constraints

- Async compatibility: Must use `async/await` patterns
- Strategy selection logic shall be stateless with respect to other requests (no cross-request mutable state)

### Requirement 3: Fail-open safety, semantic preservation, and transparency

**Objective:** As an end-user, I want compression to never break my workflows, so that I can rely on stable tool outputs even when compression is enabled.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. If a compression method raises an error or produces invalid output, the LLM Interactive Proxy shall fail open by returning the original uncompressed content to the request pipeline.
2. When compression is applied, the LLM Interactive Proxy shall preserve success/failure status and any correlation metadata associated with the original output.
3. The LLM Interactive Proxy shall not reorder multi-part outputs relative to their original sequence within a request.
4. Where compression removes or truncates information, the LLM Interactive Proxy shall include an explicit compression marker indicating that compression occurred and which method was applied (unless marker insertion is disabled by configuration).
5. If applying a compression method would increase the serialized size of the output, the LLM Interactive Proxy shall not apply that method and shall fall back to the original output.
6. If multiple compression methods are applied sequentially and any intermediate step fails, the LLM Interactive Proxy shall return the last successfully compressed result or the original output, and shall not propagate the intermediate failure to the request pipeline.

#### Technical Constraints

- Error hierarchy: Exceptions extend `LLMProxyError`

### Requirement 4: RTK-inspired generic compression primitives

**Objective:** As an agent user, I want noisy outputs to be reduced using proven primitives, so that the LLM receives high-signal context with fewer tokens.

**Priority:** P1 (High)

#### Acceptance Criteria

1. When an output contains terminal control sequences (for example: ANSI color codes, cursor movement, progress spinners), the LLM Interactive Proxy shall normalize or remove them.
2. When an output contains repeated identical lines or blocks, the LLM Interactive Proxy shall deduplicate them and shall include counts for removed duplicates.
3. When an output contains many similar items (for example: file paths, diagnostics, resource names), the LLM Interactive Proxy shall group items by a deterministically inferable key (for example: directory prefix, diagnostic rule, severity level).
4. When an output exceeds configured size thresholds, the LLM Interactive Proxy shall apply truncation rules that preserve error sections and retain a representative sample of remaining content.
5. Where compression levels are configured, the LLM Interactive Proxy shall adjust the aggressiveness of filtering, grouping, deduplication, and truncation according to the selected level.
6. When the LLM Interactive Proxy processes a tool output that matches a configurable full-output pattern and no configured exclusion guard pattern is present in the output, the LLM Interactive Proxy shall replace the output with a configured short replacement message (for example: matching "Build succeeded.*0 errors" and replacing with "build: ok", unless an error-indicating pattern is also present).
7. If all applied compression methods produce an empty result from non-empty input, the LLM Interactive Proxy shall emit a configurable per-rule fallback message (for example: "tool: ok") instead of returning empty content.
8. When an output represents a unified diff or patch, the LLM Interactive Proxy shall apply diff-aware compression that preserves per-file change statistics, retains hunk headers and bounded changed lines per hunk, and truncates oversized hunks deterministically while preserving error-relevant sections.

#### Technical Constraints

- Each primitive shall be implementable as an independent, stateless strategy to enable composition and isolated testing.
- DI integration: Primitives registered as compression strategies via `ServiceCollection`.

### Requirement 5: Tool and application coverage (broad and extensible)

**Objective:** As an operator, I want compression to cover a broad set of common development tools and be extensible, so that token savings apply across workflows.

**Priority:** P1 (High)

#### Acceptance Criteria

1. The LLM Interactive Proxy shall provide compression behavior for at least the following tool/output categories: git outputs (status, diff, log, show, branch, and mutating commands), diff/patch outputs (unified diffs from any source), file listings (tree/ls), file reads, search results (grep/rg-like), test runner outputs (pytest, vitest, go test, cargo test, rspec, minitest, playwright, .NET test/TRX), linter/typechecker outputs (ruff, mypy, eslint, tsc, rubocop, golangci-lint, clippy), build outputs (cargo, make, gradle, maven, dotnet build, gcc, swift), formatter outputs (black, prettier, biome, ruff format, dotnet format), container/kubernetes outputs, cloud CLI outputs (for example: AWS CLI, gcloud, terraform, helm, ansible), infrastructure CLI outputs (systemctl, ssh, rsync), GitHub CLI outputs (pr, issue, run, repo, checks), package manager outputs (pip, npm, pnpm, brew, bundle, composer, poetry, uv, cargo install), database CLI outputs (for example: psql), and HTTP/JSON dumps (curl, wget responses).
2. Where the originating tool/command is known, the LLM Interactive Proxy shall prefer a tool-specific compression behavior tuned for that tool over generic primitives.
3. Where the originating tool/command is unknown, the LLM Interactive Proxy shall fall back to content-shape-based compression using safe generic primitives from Requirement 4.
4. The LLM Interactive Proxy shall allow operators to disable compression for specific tools, commands, or categories via feature flags.
5. The LLM Interactive Proxy shall support adding new tool-specific compression behaviors without requiring changes to existing compression strategies or client integrations.
6. When an output corresponds to a successful side-effect command with low diagnostic value (for example: git add/commit/push/pull, branch/fetch, package install/update), the LLM Interactive Proxy shall emit a compact acknowledgement summary preserving key outcome identifiers (for example: commit hash, branch, changed-file counts) instead of verbose transport or progress text.
7. For high-volume informational command outputs (for example: git status/log/diff summaries and dependency/listing outputs), the LLM Interactive Proxy shall support stats-first reductions that preserve aggregate counts/deltas/status buckets and a bounded representative sample of detailed entries.
8. When a tool output or its associated tool call arguments contain indicators that the user explicitly requested a specific output format (for example: `--json`, `--format`, `--stat`, `--numstat` flags), the LLM Interactive Proxy shall prefer format-aware compression or passthrough over generic text compression to avoid corrupting structured user-requested output.

#### Technical Constraints

- Tool identity detection shall use the existing `ToolCategory` and `categorize_tool()` infrastructure (currently in `src/core/domain/compaction.py`; to be extracted to a shared domain location), extended as needed for new categories.
- New tool-specific strategies shall be registrable via the strategy registry without modifying orchestration code.

### Requirement 6: File listing and search-result compression

**Objective:** As an agent user, I want file listings and search results to be compact and navigable, so that I can identify relevant files quickly without flooding context.

**Priority:** P1 (High)

#### Acceptance Criteria

1. When an output represents a directory listing with many paths, the LLM Interactive Proxy shall compress it into a hierarchical summary that preserves directory structure.
2. When an output represents search results with many matches, the LLM Interactive Proxy shall group matches by file and shall deduplicate repeated match lines where safe.
3. When search output includes surrounding context lines, the LLM Interactive Proxy shall preserve context around matches up to configured limits and shall truncate additional context deterministically.
4. The LLM Interactive Proxy shall allow operators to disable listing and search-result compression independently via feature flags.
5. For compressed search results, the LLM Interactive Proxy shall preserve actionable anchors (file path and line number when present) so follow-up read/edit actions can target exact locations deterministically.
6. Where directory listing compression is enabled, the LLM Interactive Proxy shall support filtering well-known noise directories (for example: `node_modules`, `.git`, `target`, `__pycache__`, `.venv`, `vendor`) from listing outputs, with the noise directory list configurable by operators.

### Requirement 7: File-content detail levels (RTK-style read levels)

**Objective:** As an agent user, I want large file reads to be compressible into different detail levels, so that I can choose structure-first exploration without losing the ability to drill down later.

**Priority:** P1 (High)

#### Acceptance Criteria

1. Where file-content compression is enabled, the LLM Interactive Proxy shall support multiple detail levels for large file outputs (for example: full text, structure-only, signatures-only).
2. When a reduced-detail level is used, the LLM Interactive Proxy shall preserve enough structure to identify top-level entities and shall mark omitted regions explicitly.
3. If structure extraction fails for a file, or if a reduced-detail transform yields empty output for a non-empty input, the LLM Interactive Proxy shall fall back to a safer level (for example: generic truncation or original content) as configured and shall record the fallback decision for troubleshooting.
4. Where a detail level is not explicitly configured for a file output, the LLM Interactive Proxy shall select a detail level automatically based on output size and the active compression level from Requirement 2.
5. The LLM Interactive Proxy shall determine file type for detail-level selection using file extension or content heuristics, and shall treat unrecognized file types as plain text.
6. Where line-oriented navigation is configured, the LLM Interactive Proxy shall preserve or add deterministic line-number annotations for compressed file-read outputs.
7. Where line-window reduction is configured, the LLM Interactive Proxy shall support deterministic head-like (`max_lines`) and tail-like (`last_n_lines`) reductions for large file outputs.
8. For data-oriented file types (for example: JSON, YAML, TOML, XML, CSV, env, markdown), the LLM Interactive Proxy shall avoid code-comment/body stripping transforms that can corrupt literals and shall use structure-safe reductions or fail-open passthrough.

#### Technical Constraints

- Structure extraction is language-dependent; initial implementation may support a limited set of common file types (for example: Python, JavaScript/TypeScript, JSON, YAML) and shall fall back to generic truncation for unsupported types.

### Requirement 8: Failure-focused compression for tests, linting, and builds

**Objective:** As a developer, I want test/lint/build outputs to prioritize failures and actionable diagnostics, so that success noise does not dominate context.

**Priority:** P1 (High)

#### Acceptance Criteria

1. When a test runner output contains both passing and failing results, the LLM Interactive Proxy shall prioritize retaining failures and error details over passing summaries.
2. When a linter/typechecker output contains multiple diagnostics, the LLM Interactive Proxy shall group diagnostics by file and by rule/code where available.
3. Where an output indicates success with no actionable details, the LLM Interactive Proxy shall compress it to a minimal confirmation summary.
4. If compression would remove the only available failure context, the LLM Interactive Proxy shall retain the relevant failure sections unmodified.
5. The LLM Interactive Proxy shall integrate existing pytest output compression as a specialized instance of failure-focused compression, preserving its current behavior unless explicitly overridden by new dynamic compression settings (see Requirement 11).

### Requirement 9: Structured data and log compression (JSON, NDJSON, XML, noisy logs)

**Objective:** As an agent user, I want structured and log outputs to be reduced to their meaningful shape and errors, so that large payloads remain usable.

**Priority:** P1 (High)

#### Acceptance Criteria

1. When an output is valid JSON and exceeds configured thresholds, the LLM Interactive Proxy shall emit a structure-only representation that preserves keys and types while omitting values (unless disabled by configuration), applying configurable depth limits, key count caps per object, array element caps (retaining representative elements with count annotations), and long string value truncation with type/length annotations (for example: `string[1234]`, `url`, `date`).
2. When an output is line-delimited JSON (NDJSON), the LLM Interactive Proxy shall summarize repeated record shapes and shall provide counts by shape/key.
3. When an output is a log stream with repeated or near-repeated lines/blocks, the LLM Interactive Proxy shall normalize volatile fields (for example: timestamps, UUIDs, numeric IDs, hashes, ephemeral paths) for grouping and deduplication while preserving representative originals and error-indicating entries.
4. If parsing or structured-shape detection fails for a payload expected to be machine-parseable (JSON, NDJSON, XML, or an operator-declared structured format), the LLM Interactive Proxy shall follow configured fail-open behavior by either returning the original payload unchanged or applying only explicitly approved plain-text fallback rules for that format.
5. For machine-parseable structured outputs (including JSON, NDJSON, XML, and any operator-declared structured format), the LLM Interactive Proxy shall preserve syntactic validity and machine parseability after compression.
6. Where compression markers or metadata are enabled for machine-parseable structured outputs, the LLM Interactive Proxy shall emit those markers or metadata out of band and shall not inject inline annotations that break payload syntax.
7. For sensitive-output categories (for example: environment-variable dumps and cloud control-plane payloads), the LLM Interactive Proxy shall apply strategy-specific sensitive-field projection/masking by default, while allowing explicitly configured exceptions for commands whose primary purpose is secret retrieval.

### Requirement 10: Observability, auditing, and troubleshooting

**Objective:** As an operator, I want evidence and metrics for compression decisions, so that I can debug issues and quantify token savings.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. The LLM Interactive Proxy shall record per-output compression metadata including original size, compressed size, method(s) applied, and elapsed processing time.
2. Where wire capture is enabled, the LLM Interactive Proxy shall capture enough information to correlate compressed outputs with their original sources for debugging, subject to configured retention and redaction policies.
3. When compression is applied, the LLM Interactive Proxy shall expose aggregate metrics suitable for tracking byte/token savings over time.
4. If a compression method produces frequent failures or fallbacks, the LLM Interactive Proxy shall surface this in logs or metrics to enable remediation.
5. When compression truncates output beyond configured thresholds, the LLM Interactive Proxy shall optionally persist a bounded raw-output recovery artifact and emit a redaction-safe recovery handle in diagnostics (and in-text hints for plain-text outputs when marker policy permits), without failing request processing if artifact persistence is unavailable.

#### Technical Constraints

- Compression metadata shall be compatible with the existing structured logging and CBOR wire-capture infrastructure.
- Metrics shall be emittable via existing logging/metrics patterns without introducing new external dependencies.

### Requirement 11: Backward compatibility and migration safety

**Objective:** As an operator, I want migration from existing compression features to be safe and predictable, so that current workflows do not regress during rollout.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. The LLM Interactive Proxy shall preserve existing behavior for current context compaction and pytest compression unless explicitly overridden by new dynamic compression settings.
2. When legacy controls and new dynamic compression controls are both configured, the LLM Interactive Proxy shall resolve them using a deterministic and documented precedence model.
3. If conflicting settings create ambiguous behavior, the LLM Interactive Proxy shall fail open for the affected compression behavior and shall emit an operator-visible warning describing the effective fallback.
4. Where overlapping compression features are enabled for the same content path (for example: connector-level truncation and dynamic compression), the LLM Interactive Proxy shall avoid double-reduction of the same payload in a single request flow.
5. The LLM Interactive Proxy shall provide migration diagnostics indicating which compression settings were applied, ignored, or overridden.

#### Technical Constraints

- Legacy configuration fields (`compaction.*`, `session.pytest_compression_enabled`, connector-level `truncate_tool_outputs`) shall remain functional during migration.
- Configuration drift identified in the gap analysis (unused `stub_template`, unwired `max_stubs_per_resource`, `preserve_last_n_results`) shall be resolved: either wired to runtime behavior or explicitly deprecated with operator-visible warnings.

### Requirement 12: Configuration surface integrity

**Objective:** As an operator, I want every documented compression control to have a clear runtime effect or explicit warning, so that configuration is trustworthy and auditable.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. When a documented compression configuration option is provided (YAML, ENV, or CLI), the LLM Interactive Proxy shall either apply that option at runtime or emit a clear warning that the option is unsupported or inactive.
2. The LLM Interactive Proxy shall expose effective compression configuration state for diagnostics in a redaction-safe form.
3. If a compression option is accepted but inactive due to current runtime context, then the LLM Interactive Proxy shall log the reason and affected scope.
4. The LLM Interactive Proxy shall keep configuration behavior deterministic across repeated startups with the same effective inputs.

### Requirement 13: Operator-definable declarative compression rules

**Objective:** As an operator, I want to define compression rules via configuration without code changes, so that I can extend compression coverage to new tools and customize output reduction behavior without deploying new proxy versions.

**Priority:** P1 (High)

#### Acceptance Criteria

1. The LLM Interactive Proxy shall support declarative, configuration-defined compression rules that operators can define without code changes (for example: via YAML rule definitions within the compression configuration block or loaded from separate rule files).
2. Each declarative rule shall support at least the following composable primitives applied in sequence: ANSI stripping, regex-based line replacement, full-output pattern matching with short-message replacement (including exclusion guard patterns), line-pattern-based inclusion or exclusion (keep/strip lines matching), per-line length truncation, head/tail line limits, maximum line count, and empty-result fallback message.
3. Declarative rules shall be matched to tool outputs using configurable predicates (for example: command prefix regex, tool category, tool name pattern) with deterministic match ordering.
4. Where a declarative rule and a code-based compression strategy both match the same output, the LLM Interactive Proxy shall resolve the conflict using a deterministic, documented precedence model (by default: code-based strategies take precedence, unless the declarative rule is explicitly configured as an override).
5. The LLM Interactive Proxy shall validate declarative rule definitions at startup and shall fail open with operator-visible warnings for invalid or malformed rules.
6. The LLM Interactive Proxy shall ship a set of built-in declarative rules covering common development tools not handled by specialized code-based strategies, to maximize out-of-the-box tool coverage.

#### Technical Constraints

- Declarative rules must use the same eligibility, fail-open, marker, and observability contracts as code-based strategies.
- Declarative rule evaluation must be bounded (configurable time budget, bounded regex complexity) to prevent catastrophic backtracking or event-loop starvation.

### Requirement 14: Legacy compression code unification and removal

**Objective:** As an operator, I want the proxy to have a single, unified compression architecture instead of multiple concurrent implementations of similar functionality, so that behavior is predictable, maintainable, and configurable from one place.

**Priority:** P1 (High)

#### Acceptance Criteria

1. After the dynamic compression subsystem is verified stable, all pytest output filtering logic currently in `ResponseManagerService` (`_apply_pytest_compression_sync`, `_filter_pytest_output`, `_filter_pytest_output_with_metrics`) shall be removed and replaced by the `pytest_failure_focus` strategy in the dynamic compression pipeline.
2. After the dynamic compression subsystem is verified stable, the standalone pytest detection pipeline (`PytestCompressionService`, `PytestCompressionHandler`) shall be removed and its detection responsibilities unified into `ToolIdentityResolver`.
3. After the dynamic compression subsystem is verified stable for Gemini-bound requests, the Gemini connector-level tool-output truncation (`_truncate_tool_outputs_if_configured` in `ChatRequestPreparer`) shall be removed and replaced by dynamic compression.
4. Dead code identified during the legacy inventory (the `compress_next_tool_call_reply` session flag, which is written but never read) shall be removed immediately as a prerequisite cleanup.
5. Legacy configuration fields being sunset (`session.pytest_compression_enabled`, `pytest_compression_min_lines`, `PYTEST_COMPRESSION_MIN_LINES`, CLI `--enable-pytest-compression`/`--disable-pytest-compression`, Gemini `tool_output_truncate_*` extras and env vars) shall emit operator-visible deprecation warnings when set, and shall be removed after one release cycle.
6. Before any legacy code is removed, contract tests shall verify behavioral equivalence between the legacy implementation and its dynamic compression replacement using representative inputs, including edge cases from current production usage patterns.
7. The dynamic compression pipeline shall detect and skip already-processed tool outputs (compaction stubs, artifact preview markers) to avoid double-processing content modified by other tool-output services that remain active (`HistoryCompactionService`, `ArtifactService`).

#### Technical Constraints

- Legacy removal is gated on verified behavioral equivalence (contract tests), not on a calendar schedule.
- The pytest output filtering pipeline position shifts from response formatting (before history storage) to backend request preparation (before backend translation). This is intentional: the new position preserves original content in history for different backends and enables recompression under budget pressure. Contract tests must account for this positional change.
- Features explicitly out of scope for unification: `ArtifactService` (artifact preview management), `stringify_tool_calls_and_results` (role downgrade for non-tool-supporting backends), `QualityVerifierService` history sanitization.

## Out of Scope

- Shell-hook mechanics or terminal-integration patterns from RTK (the proxy operates at the API layer, not the shell layer).
- Client SDK changes or new client-facing API endpoints for compression control (compression is transparent to clients).
- Modifications to backend provider API schemas (OpenAI, Anthropic, Gemini).
- Changes to the CBOR wire-capture binary format or storage layout.
- Compression of streaming response chunks in-flight (compression targets tool outputs in request context, not streaming response payloads).
- Real-time compression configuration changes within an active request (configuration applies at request boundaries).
- Adding new user-facing features or changing observable API behavior beyond compression markers in tool outputs.
- Unification of `ArtifactService` artifact preview management (separate concern: file content expansion/compression, not token reduction).
- Unification of `stringify_tool_calls_and_results` role-downgrade truncation (separate concern: backend compatibility for non-tool-supporting backends). The hard-coded `max_tool_result_chars=2000` limit should be revisited in a future iteration.
- Unification of `QualityVerifierService` history sanitization (separate concern: verifier model input preparation).

## Non-Functional Requirements

### NFR 1: Performance

- The LLM Interactive Proxy shall support a configurable time budget for compression per output (default: no more than 100ms per individual output) and shall fail open when the budget is exceeded.
- The LLM Interactive Proxy shall support configuring size thresholds that bound the work performed by compression on extremely large outputs.
- The LLM Interactive Proxy shall not introduce measurable latency overhead on requests where compression is disabled or where no outputs are eligible for compression.

### NFR 2: Reliability

- The LLM Interactive Proxy shall not fail request processing solely due to compression errors.
- The LLM Interactive Proxy shall be able to run with compression enabled without increasing error rates in core request routing paths.

### NFR 3: Determinism and reproducibility

- Given the same input, configuration, and compression level, the LLM Interactive Proxy shall produce the same compressed result deterministically.
- The LLM Interactive Proxy shall ensure compressed outputs are stable enough for contract tests to pin behavior.

### NFR 4: Security and privacy

- Where outputs may contain secrets or credentials, the LLM Interactive Proxy shall support redaction controls that apply consistently to both compressed outputs and any retained raw artifacts.
- The LLM Interactive Proxy shall allow operators to disable any retention of original uncompressed outputs used solely for troubleshooting.
- Any troubleshooting retention of uncompressed outputs shall support bounded storage controls (mode, max artifact size/count, and retention horizon) with secure defaults.

### NFR 5: Compatibility and rollout safety

- The LLM Interactive Proxy shall support phased rollout of dynamic compression features without requiring client integration changes.
- The LLM Interactive Proxy shall keep legacy compression controls operational during migration to generalized compression controls.
- The LLM Interactive Proxy shall preserve fail-open behavior as the default safety mode during migration and partial feature adoption.

## Execution Guardrails (Agent Instructions)

These guardrails are process constraints intended to prevent common failure modes during implementation of this XL-effort, high-risk feature. They are additive to the requirements above and are treated as non-negotiable constraints.

### Mandatory: Consult RTK Reference Implementation Before Coding

The RTK source code is cloned at `./dev/thrdparty/rtk/` and contains **proven, well-tested implementations** in Rust for every compression primitive and tool-specific filter in this spec. **Agents MUST consult the relevant RTK source files before implementing each task.** Do not reinvent algorithms or guess at output-processing heuristics when a working reference exists. Translate patterns from Rust to Python faithfully, adapting only for the proxy's async/DI architecture. The design document and each task in the implementation plan include `_RTK ref:_` lines pointing to specific source files and line numbers.

### Mandatory: Test-Driven Development (TDD)

All implementation MUST follow strict TDD methodology:
1. **RED**: Write failing tests FIRST, before any production code. Tests should assert the expected compression behavior based on RTK's proven output patterns.
2. **GREEN**: Write minimal production code to make tests pass.
3. **REFACTOR**: Clean up code structure while keeping tests green.

Use RTK's own test fixtures (`dev/thrdparty/rtk/tests/fixtures/`) and the inline test cases in RTK source files (search for `#[cfg(test)]` / `mod tests`) as a source of realistic test inputs and expected outputs. Port representative test cases to Python before implementing the corresponding strategy.

### Must Avoid

- Do not create a new god-service that accumulates all compression responsibilities in a single class or module; decompose into focused strategy implementations behind a shared interface.
- Do not break existing `HistoryCompactionService` or `PytestCompressionService` tests during migration; these are behavior contracts.
- Do not bypass DI for strategy construction; all compression strategies shall be wired through `ServiceCollection`.
- Do not apply compression to streaming response chunks in-flight; compression targets tool outputs in request context before backend translation.
- Do not introduce synchronous blocking calls in compression strategy implementations.
- Do not hardcode tool/command detection strings in strategy implementations; use the existing `ToolCategory` / `categorize_tool()` infrastructure or its documented extensions.
- Do not import or raise FastAPI/Starlette types from compression service modules; normalize to domain errors and let transport map to HTTP.
- Do not guess at filtering heuristics, regex patterns, or output-processing algorithms when the RTK source code provides a proven reference. Always consult the referenced RTK files first.
- Do not write production code before writing failing tests. TDD is mandatory for every task.

### Mandatory Verification (Before marking any task complete)

- Run the relevant focused tests for changed modules, then run the full automated test suite with zero failures.
- Verify fail-open behavior by confirming that a deliberately broken compression strategy does not propagate errors to the request pipeline.
- Confirm that outputs compressed by the new system include expected compression markers and metadata structure.
- Confirm that test cases include representative inputs derived from RTK's own test fixtures and inline tests where available.

## Glossary

| Term | Definition |
|------|------------|
| Compression system | Proxy subsystem that reduces output size before sending context onward |
| Compression strategy | A named, registrable implementation of a specific compression technique (for example: deduplication, ANSI stripping, JSON structure-only) |
| Compression method | A deterministic transformation that reduces output size (filter/group/dedup/truncate, etc.) |
| Compression pipeline | The ordered sequence of compression strategies applied to a single output |
| Compression level | Operator-configured aggressiveness tier that changes how methods behave |
| Compression marker | An explicit annotation inserted into compressed output indicating that compression occurred and which method was applied |
| Dynamic compression | Selecting and applying compression based on metadata, content shape, size, and token budget |
| Content shape | Observable structural characteristics of an output (for example: line count, JSON validity, presence of ANSI codes) used for strategy matching when tool identity is unknown |
| Feature flag | Configuration toggle used to enable/disable a compression behavior safely |
| Fail open | On error or uncertainty, bypass compression and return original output |
| Tool output | Content produced by a tool/command execution path that may be included in LLM context |
| Tool category | A classification of the tool that produced an output (for example: git, test runner, linter), used for strategy selection; see existing `ToolCategory` and `categorize_tool()` |
| History compaction | The existing mechanism that replaces stale tool outputs with summary stubs between conversation turns (also called "context compaction" in the configuration surface) |
| Wire capture | CBOR-encoded binary recording of request/response traffic for debugging and replay |
| RTK | The open-source reference project `rtk-ai/rtk` providing compression techniques to replicate |
| Declarative rule | A configuration-defined compression rule (not code) that specifies match predicates and a sequence of text-processing primitives |
| Output pattern match | A full-output regex test that can short-circuit compression by replacing the entire output with a configured message |
| Exclusion guard pattern | A regex applied before pattern matching to prevent false-positive replacements when error indicators are present |
| Noise directory | A well-known directory (for example: `node_modules`, `.git`, `target`) that typically adds noise to listing outputs and can be filtered |
| Diff-aware compression | Compression that understands unified diff structure (file headers, hunks, +/- lines) and applies hunk-level truncation |
