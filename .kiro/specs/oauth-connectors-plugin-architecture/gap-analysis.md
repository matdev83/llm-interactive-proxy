# Gap Analysis: oauth-connectors-plugin-architecture

## 1. Current State Investigation

- **Key Files & Modules**:
  - `src/connectors/oauth_detector.py`: Multi-layered detection with hardcoded `KNOWN_OAUTH_CONNECTORS` set (6 hardcoded entries: `gemini-cli-acp`, `cursor-cli-acp`, `openai-codex`, `opencode-zen`, `cline`, `kiro-oauth-auto` — plus dynamically resolved extracted backends via `get_extracted_backend_names()`), naming patterns (`_oauth_`, `_oauth`), and `has_static_credentials=False` property check. Already has **partial** dynamic capability through entry-point discovery.
  - `src/core/cli_support/argument_parser_builder.py`: Contains **9 hardcoded** backend-specific debugging override flags in `_add_debugging_override_arguments` (e.g., `--enable-gemini-oauth-auto-backend-debugging-override`, `--enable-kiro-oauth-auto-backend-debugging-override`, `--enable-opencode-zen-backend-debugging-override`). Additionally has 3 deferred in-repo OAuth behavior flags: `--disable-gemini-oauth-fallback`, `--disable-gemini-oauth-reasoning-prompt-injection`, `--allow-oauth-auto-replacement`.
  - `src/core/services/resilience/scope.py`: Hardcoded `_PERSONAL_BACKEND_TYPES` frozenset with **7 entries** (`antigravity-oauth`, `gemini-cli-cloud-project`, `gemini-oauth-free`, `gemini-oauth-plan`, `openai-codex`, `opencode-zen`, `qwen-oauth`) plus a fallback `"oauth" in normalized or "codex" in normalized` substring heuristic. Supports runtime config overrides via `resilience.shared_backend_types` / `resilience.personal_backend_types`.
  - `src/connectors/gemini_base/streaming_executor.py`: Already defines `ITokenRefresher` protocol (`refresh_token_if_needed(force_reload, session_id, retry_after_seconds) -> bool`) but retains legacy duck-typing: `_is_oauth_auto_refresher` (checks `"oauth-auto" in backend_type`), `_apply_refreshed_auth_header` (accesses `_oauth_credentials`), `_get_oauth_auto_selection_strategy` / `_get_oauth_auto_available_account_count` (access `_account_selector`), and `_record_rate_limit` (duck-typed `getattr`).
  - `tests/unit/connectors/test_qwen_oauth_retry.py` and `tests/unit/connectors/test_vendor_prefix.py` (L127): The core test suite explicitly imports the `llm-interactive-proxy-oauth-connectors` package via `pytest.importorskip`.

- **Conventions & Patterns**:
  - The system relies on string matching and naming conventions (`-oauth-`) to identify capabilities, rather than explicit metadata.
  - Core execution logic (like `streaming_executor.py`) is tightly coupled to the internal state of specific plugins.
  - The core test suite treats the optional plugin package as if it were part of the core repository.

## 2. Requirements Feasibility Analysis

- **Core Independence from Plugin Names**: Feasible. Requires replacing hardcoded lists in `oauth_detector.py` and `scope.py` with **capability flags** on `BackendCapabilityDescriptor` (not a separate global registry). Note: `oauth_detector.py` already has partial dynamic capability via entry-point discovery; the refactor formalizes and completes this.
- **Capability Declaration**: Feasible. The `BackendCapabilityDescriptor` needs to be extended with `requires_personal_auth` and `is_oauth_based` flags. Pydantic v2 `model_validate` handles new fields with defaults automatically.
- **Execution Decoupling**: Feasible. `streaming_executor.py` already defines `ITokenRefresher` protocol. New `ICredentialRotator` (extending `ITokenRefresher`) and `IOAuthAccountSelector` protocols must be defined in `src/core/interfaces/`. `ICredentialRotator` also adds `get_current_access_token()` and `record_rate_limit()` to replace remaining duck-typed access patterns. `ITokenRefresher` must be relocated from `streaming_executor.py` to `src/core/interfaces/`.
- **Configuration and CLI Independence**: Feasible but requires architectural changes. The `ConfigurationApplicator` uses a domain-specific applicator delegation pattern (15+ applicators); plugin hooks should be invoked as a post-applicator phase. The 9 debug override flags and 3 deferred CLI flags need careful classification.
- **Test Isolation**: Highly feasible. Requires moving OAuth-specific tests (`test_qwen_oauth_retry.py`, relevant cases in `test_vendor_prefix.py`) to the `llm-interactive-proxy-oauth-connectors` repository and using mock plugins for testing discovery in the core repo.

- **Gaps & Constraints**:
  - *Missing Capability*: No mechanism currently exists for plugins to dynamically inject CLI arguments into the core `argparse` setup.
  - *Partially Addressed*: `ITokenRefresher` protocol exists in `streaming_executor.py` but needs relocation to `src/core/interfaces/`. No generic interfaces exist for credential rotation, rate-limit recording, credential snapshot access, or account selection beyond `ITokenRefresher`.
  - *Existing Dynamic Capability*: `oauth_detector.py` already partially resolves backends via entry-point discovery (`get_extracted_backend_names()`); this partial decoupling should be acknowledged and extended rather than replaced from scratch.
  - *Runtime Config Overrides*: `scope.py` already supports runtime config overrides via `resilience.shared_backend_types` / `resilience.personal_backend_types`, which reduces urgency of removing hardcoded defaults.

## 3. Implementation Approach Options

### Option A: Extend Existing Plugin Discovery (Recommended)
**Approach**: Enhance the existing `BackendCapabilityDescriptor` and plugin discovery mechanism to support capability flags and CLI argument registration. Define new interfaces in `src/core/interfaces/` for execution decoupling.

**Trade-offs**:
- ✅ Aligns with the existing plugin architecture.
- ✅ Cleanly separates concerns by using interfaces.
- ❌ Requires modifying the core CLI builder and discovery logic.

### Option B: Event-Driven Hooks
**Approach**: Introduce an event system where plugins can subscribe to events like `on_cli_build` or `on_credential_rotation_needed`.

**Trade-offs**:
- ✅ Extremely decoupled.
- ❌ Introduces significant architectural complexity (event bus) that may not be justified for this specific problem.

## 4. Implementation Complexity & Risk

- **Effort**: **L (1-2 weeks)**. Requires significant refactoring of core execution paths (`streaming_executor.py`), CLI building, and moving a large number of tests across repository boundaries.
- **Risk**: **Medium**. The changes touch critical paths (streaming execution, CLI startup), but the goal is to formalize existing implicit contracts into explicit interfaces, which is a known and safe pattern.

## 5. Recommendations for Design Phase

- **Preferred Approach**: Option A (Extend Existing Plugin Discovery). Focus on relocating/extending existing `ITokenRefresher`, defining `ICredentialRotator` (extending `ITokenRefresher`) and `IOAuthAccountSelector`, and extending `BackendCapabilityDescriptor`.
- **Research Needed**:
  - How to safely allow plugins to register CLI arguments without causing conflicts or breaking the `argparse` lifecycle.
  - The exact shape of the generic interfaces needed by `streaming_executor.py` to replace `_oauth_credentials`, `_account_selector`, and `record_rate_limit` access. (Largely resolved in `design.md` migration path table.)
