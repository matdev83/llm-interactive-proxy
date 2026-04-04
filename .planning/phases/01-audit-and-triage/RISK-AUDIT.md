# Risk Audit

**Phase:** 01-audit-and-triage
**Date:** 2026-04-04
**Auditor:** Antigravity

## 1. Loop Detection Gap

### Finding: LoopBreakingService is Dead Code

**Severity: LOW** (detection still works, only the "breaking" feature is wired off)

| Item | Detail |
|------|--------|
| File | `src/core/services/loop_breaking_service.py` |
| Lines | 1-271 |
| Status | **Dead code** -- defined but never imported by any production module |

**Evidence:**
- `grep -r "LoopBreakingService" src/` returns only the definition file itself.
- `grep -r "loop_breaking_service" src/` returns zero production imports.
- The class implements API cancellation and steering message injection on loop detection, but is not wired into any DI registration or startup stage.

**Current state of loop detection:**
- `LoopDetectionProcessor` (`src/core/domain/streaming_response_processor.py`) is properly registered via `_register_loop_detection_processor()` in `_streaming_pipeline.py`.
- `HybridLoopDetector` is properly wired as `ILoopDetector`.
- Loop **detection** works. Loop **breaking** (cancel API + steering retry) does not -- the `LoopBreakingService` that was supposed to provide this is dead.
- Interactive commands `!/loop-detection`, `!/tool-loop-detection`, `!/tool-loop-ttl`, `!/tool-loop-mode`, `!/tool-loop-max-repeats` all work and are registered in both command systems.

**Risk:** When a loop is detected, the system detects it but the breaking logic (API cancellation + steering message + retry) never fires. The user sees loop detection logs but no automatic recovery.

**Recommendation:** `needs-phase` -- Wire `LoopBreakingService` into the streaming pipeline or remove the dead code.

---

## 2. MCP Placeholder Scope

### Finding: UniversalMCPClient is Fully Placeholder

**Severity: MEDIUM**

| Item | Detail |
|------|--------|
| File | `src/core/services/universal_mcp_client.py` |
| Lines | 1-407 |
| Status | **Placeholder** -- all core methods contain TODO comments and return simulated data |

**Evidence (key placeholder locations):**

| Method | Line | Comment |
|--------|------|---------|
| `connect_to_server()` | 105 | `# TODO: Implement actual MCP server connection` |
| `_discover_server_tools()` | 149 | `# TODO: Implement actual tool discovery via MCP protocol` |
| `execute_tool()` | 220-225 | `# TODO: Implement actual tool execution via MCP protocol` |
| `read_resource()` | 274 | `# TODO: Implement actual MCP resource reading via MCP protocol` |
| `_send_tool_call()` | 316 | `# TODO: Implement actual MCP protocol communication` |

**Current behavior:**
- `connect_to_server()` stores config in a dict and returns `True` (always succeeds)
- `_discover_server_tools()` always discovers zero tools
- `execute_tool()` returns a simulated success string
- `read_resource()` returns a placeholder string
- The client has proper class structure, error handling, and type annotations -- only the protocol communication is missing

**Risk:** If any integration activates MCP tool injection, all tool calls would silently return fake results. No production path currently calls this client, so the risk is latent.

**Recommendation:** `defer` -- This is an intentional future feature. Add a `# PLACEHOLDER` banner at the module level so future developers don't accidentally integrate it.

---

## 3. MagicMock Production Fallback

### Finding: 6 Production Files Import unittest.mock

**Severity: HIGH**

| # | File | Line | What gets mocked | Trigger |
|---|------|------|-----------------|---------|
| 1 | `src/core/app/controllers/__init__.py` | 175 | `IRequestProcessor` via `MagicMock(spec=IRequestProcessor)` | AnthropicController factory function fails AND `IRequestProcessor` is not resolved |
| 2 | `src/core/app/application_factory.py` | 52 | `AppConfig` via `isinstance(config, MagicMock)` check | Config validation when `isinstance` check itself throws `TypeError` |
| 3 | `src/core/di/registration_helpers/request_processing/_rp_orchestration_core.py` | 393 | `IQualityVerifierServiceFactory` via `MagicMock(spec=...)` | `IQualityVerifierServiceFactory` not registered in DI |
| 4 | `src/core/di/registrations/_streaming_pipeline.py` | 416 | `orchestrator`, `stream_context_resolver`, `tool_call_reactor` via `MagicMock()` | Any of the 3 ToolCallReactor dependencies is None |
| 5 | `src/core/transport/fastapi/adapters/sanitization/json_sanitizer.py` | 36 | `AsyncMock` type caching for sanitization | Always (module init imports AsyncMock for isinstance checks) |
| 6 | `src/core/app/stages/test_stages.py` | 13 | Various test mocks | Test-only file in `src/` tree |

**Analysis of each:**

1. **controllers/__init__.py:175** -- This is the most dangerous occurrence. If the Anthropic controller factory fails, it creates a `MagicMock(spec=IRequestProcessor)` and feeds it to `AnthropicController`. This means a production Anthropic request could be handled by a mock that returns `{"choices": [{"message": {"content": "This is a test response from a mock processor"}}]}`. The fallback is deeply nested in a triple-except pattern.

2. **application_factory.py:52** -- Accepts `MagicMock` as a valid config type. This is a test accommodation that leaked into production code. Low runtime risk because tests typically don't go through this path in production.

3. **_rp_orchestration_core.py:393** -- Falls back to `MagicMock(spec=IQualityVerifierServiceFactory)` when the quality verifier factory is not in DI. The mock is passed to `BackendRequestManager` as a constructor argument. Calls to it would silently return mocks.

4. **_streaming_pipeline.py:416** -- Creates `ToolCallReactorMiddleware` with MagicMock dependencies when real services are unavailable. Mitigated by `enabled=False`, but the mock objects are still reachable.

5. **json_sanitizer.py:36** -- Caches the `AsyncMock` type at module init purely for `isinstance` checks during sanitization. This is the most defensible use -- it's using the type, not creating mock instances. **Low risk.**

6. **test_stages.py:13** -- This is a test file living in `src/core/app/stages/`. It should be in `tests/` but is not a production code risk.

**Risk:** Items 1 and 3 are the highest risk. A DI resolution failure could silently swap a real service for a mock, causing the proxy to return fake LLM responses to end users without any error.

**Recommendation:** `fix-in-place` for items 1-4 (replace MagicMock fallbacks with proper error handling or null-object patterns). `defer` for items 5-6.

---

## 4. Dead Configuration Variants

### Finding: Multiple Example Configs With Unclear Activation Status

**Severity: LOW**

| Config File | Purpose | Status |
|-------------|---------|--------|
| `config/config.example.yaml` | Main example config | **Active** (documented in README) |
| `config/config.yaml` | User's active config | **Active** (gitignored, user-managed) |
| `config/local_dev_config.yaml` | Development overrides | **Uncertain** -- unclear if loaded at runtime |
| `config/codebuff.example.yaml` | Codebuff integration config | **Dead** -- no code references loading this |
| `config/identity_factory_droid.example.yaml` | Identity config variant | **Dead** -- example only |
| `config/identity_kilocode.example.yaml` | Identity config variant | **Dead** -- example only |
| `config/qwen_backend.example.yaml` | Qwen backend config | **Dead** -- example only |
| `config/reasoning_aliases.yaml.example` | Reasoning alias mappings | **Dead** -- example only |
| `config/sso_auth.example.yaml` | SSO authentication config | **Dead** -- example only |
| `config/tool_access_control_examples.yaml` | Tool access control | **Dead** -- example only |
| `config/edit_precision_model_temperatures.yaml` | Model temperature profiles | **Uncertain** -- may be loaded by EditPrecision feature |
| `config/edit_precision_patterns.yaml` | Edit precision patterns | **Uncertain** -- may be loaded by EditPrecision feature |
| `config/tool_call_reactor_config.yaml` | Tool call reactor rules | **Uncertain** -- may be loaded by ToolCallReactor feature |
| `config/sample.env` | Environment variable example | **Dead** -- reference only |

**Risk:** Low. Example files are clearly marked with `.example` suffix. The uncertain files (`edit_precision_*`, `tool_call_reactor_config.yaml`, `local_dev_config.yaml`) may or may not be loaded at runtime depending on feature flags.

**Recommendation:** `defer` -- Add a `config/README.md` to document which files are live vs. examples.

---

## 5. Dependency Pinning Gaps

### Finding: Mixed Pinning Strategy in pyproject.toml

**Severity: MEDIUM**

**Production dependencies (`[project.dependencies]`):**

| Dependency | Specifier | Pinning | Risk |
|-----------|-----------|---------|------|
| `fastapi` | (none) | **UNPINNED** | Major version bump could break API |
| `uvicorn[standard]` | (none) | **UNPINNED** | Could break ASGI server |
| `httpx[http2]` | (none) | **UNPINNED** | HTTP client API changes |
| `python-dotenv` | (none) | **UNPINNED** | Low risk (stable API) |
| `pydantic>=2` | floor only | Minimum floor | V3 could break |
| `openai==1.84.0` | **PINNED** | Exact pin | Good |
| `tomli` | (none) | **UNPINNED** | Low risk (read-only) |
| `typer` | (none) | **UNPINNED** | CLI could break |
| `rich` | (none) | **UNPINNED** | Low risk (output only) |
| `llm-accounting` | (none) | **UNPINNED** | Internal dep -- high risk if API changes |
| `tiktoken` | (none) | **UNPINNED** | Tokenizer changes could affect counting |
| `google-genai` | (none) | **UNPINNED** | Gemini SDK -- high risk |
| `anthropic` | (none) | **UNPINNED** | Anthropic SDK -- high risk |
| `structlog` | (none) | **UNPINNED** | Low risk |
| `pyyaml` | (none) | **UNPINNED** | Low risk (stable API) |
| `jsonschema>=4.19.0` | floor only | Minimum floor | Low risk |
| `google-auth>=2.27.0` | floor only | Minimum floor | Medium risk |
| `json-repair` | (none) | **UNPINNED** | Medium risk |
| `ijson` | (none) | **UNPINNED** | Low risk |
| `watchdog` | (none) | **UNPINNED** | Low risk |
| `pytz` | (none) | **UNPINNED** | Low risk |
| `pytest-asyncio==0.23.7` | **PINNED** | Exact pin | **WRONG SECTION** -- test dep in prod deps |
| `pytest-xdist==3.6.1` | **PINNED** | Exact pin | **WRONG SECTION** -- test dep in prod deps |
| `cbor2>=5.6.0` | floor only | Minimum floor | Low risk |
| `authlib>=1.3.0` | floor only | Minimum floor | Medium risk |
| `argon2-cffi>=23.1.0` | floor only | Minimum floor | Low risk |
| `aiosqlite>=0.19.0` | floor only | Minimum floor | Low risk |
| `python-multipart>=0.0.6` | floor only | Minimum floor | Low risk |
| `ping3>=4.0.0` | floor only | Minimum floor | Low risk |
| `sqlmodel>=0.0.22` | floor only | Minimum floor | Medium risk |
| `alembic>=1.13.0` | floor only | Minimum floor | Medium risk |
| `greenlet>=3.0.0` | floor only | Minimum floor | Low risk |
| `cachetools>=5.3.0` | floor only | Minimum floor | Low risk |
| `desktop-notifier` | (none) | **UNPINNED** | Low risk |
| `websockets>=12.0` | floor only | Minimum floor | Medium risk |

**Key Issues:**

1. **Test dependencies in production:** `pytest-asyncio==0.23.7` and `pytest-xdist==3.6.1` are listed in `[project.dependencies]` instead of `[project.optional-dependencies.dev]`. This means production installs pull in pytest infrastructure.

2. **High-risk unpinned deps:** `fastapi`, `httpx`, `google-genai`, `anthropic`, and `llm-accounting` are completely unpinned. These are core dependencies whose APIs this project heavily relies on.

3. **Good pins:** `openai==1.84.0` is properly pinned. The dev dependencies in `[project.optional-dependencies.dev]` are well-pinned.

**Risk:** A routine `pip install --upgrade` could pull in breaking changes from unpinned providers (Google Genai, Anthropic, FastAPI). The test deps in production bloat the install.

**Recommendation:** `fix-in-place` for the test dep misplacement (move `pytest-asyncio` and `pytest-xdist` to dev). `needs-phase` for comprehensive dependency pinning strategy.
