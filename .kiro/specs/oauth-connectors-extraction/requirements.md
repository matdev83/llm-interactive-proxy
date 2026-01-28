# Requirements Document

## Project Description (Input)
Extract OAuth connectors (Google, etc.) from the main proxy codebase into a more modular structure or separate components to improve maintainability and support better reuse.

## Requirements

### Requirement 1: Backend Plugin Discovery
1.1 When the proxy process starts, the system shall ensure backend discovery runs early enough to populate `BackendRegistry` before backend selection is required (e.g., CLI parsing and backend initialization).
1.2 The system shall continue to discover internal backends from the core `src/connectors/` package via the existing auto-import mechanism.
1.3 When backend discovery runs, the system shall attempt to discover external backends via Python entry points in the group `llm_proxy_backends`.
1.4 If an external backend entry point cannot be loaded, the system shall log a warning with the entry point name and continue startup.
1.5 The system shall register each successfully loaded external backend factory into `BackendRegistry` under the entry point name.

### Requirement 2: Connector Extraction Scope (OAuth and Other Sensitive Backends)
2.1 The core distribution (`llm-interactive-proxy`) shall not ship the following backend implementations; they shall be provided by an external distribution (proposed name: `llm-proxy-oauth-connectors`):
2.1.1 `anthropic-oauth`
2.1.2 `antigravity-oauth`
2.1.3 `qwen-oauth`
2.1.4 `gemini-oauth-free`
2.1.5 `gemini-oauth-plan`
2.1.6 `gemini-oauth-auto`
2.1.7 `gemini-cli-cloud-project`
2.1.8 `kiro-oauth-auto`
2.1.9 `openai-codex`
2.1.10 `cline`
2.1.11 `zai`
2.1.12 `zai-coding-plan`
2.1.13 `kimi-code`
2.2 The external distribution shall define entry points under `llm_proxy_backends` for each extracted backend.
2.3 The core distribution shall expose a stable, documented plugin API surface for external backends (minimum: `LLMBackend`, `AppConfig`, and `ITranslationService` types, plus a supported registration mechanism) without requiring plugins to import from deep internal modules.
2.4 Shared connector utilities and mixins that are required by core (non-extracted) connectors shall remain in core; utilities that are only required by extracted connectors shall move with the extracted connectors.
2.5 Core DI registration code shall not unconditionally import extracted connector modules (directly or transitively); missing extracted connectors shall not break core startup.

### Requirement 3: Backward Compatibility & Runtime Behavior
3.1 The configuration model shall continue to accept YAML backend entries for extracted backend names without schema changes.
3.2 If a backend name is referenced by configuration (e.g., `default_backend`, `static_route`, or explicit backend config) but is not registered at runtime, the system shall emit an actionable warning that includes the recommended install command for the external connector distribution.
3.3 If `default_backend` or `static_route` references an unregistered backend and no other registered backend is available to serve requests, the system shall fail startup validation with an actionable error.
3.4 When a request targets an unregistered backend, the system shall return a deterministic error response rather than raising an unhandled exception.
3.5 The system shall allow startup to proceed when at least one configured backend is registered and functional, even if other configured backends are missing.

### Requirement 4: Core Connector Integrity
4.1 Non-extracted backends (at minimum: `openai`, `openai-responses`, `anthropic`, `gemini`, `openrouter`, `minimax`, `zenmux`, `opencode-zen`, `hybrid`) shall remain in core and continue to work without the external connector distribution installed.
4.2 Backend discovery shall remain fail-open for optional external backends.

### Requirement 5: Packaging and Installation UX
5.1 The core distribution (`llm-interactive-proxy`) shall provide an optional dependency extra named `oauth` that installs the external connector distribution.
5.2 The recommended installation command for full functionality shall be `pip install llm-interactive-proxy[oauth]`.
5.3 Dependencies that are only required for extracted connectors shall not be mandatory dependencies of the core distribution.

### Requirement 6: Testing & Verification
6.1 The core proxy shall include unit tests using mocks to verify external entry point discovery works without the external connector distribution installed.
6.2 The core test suite shall pass when the external connector distribution is not installed.
6.3 The external connector distribution shall include its own test suite to verify extracted connector functionality.
