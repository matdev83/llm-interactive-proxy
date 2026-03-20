# Gap Analysis: Nvidia API Backend

**Feature**: `nvidia-api-backend`  
**Spec**: `.kiro/specs/nvidia-api-backend/requirements.md`  
**Language**: English (`spec.json`)  
**Note**: `spec.json` marks requirements as generated but not yet approved; this analysis informs design and may surface requirement tweaks.

---

## 1. Current state investigation

### 1.1 Domain assets (existing)

| Area | Location / pattern |
|------|---------------------|
| Connector contract | `LLMBackend` in `src/connectors/base.py` (`backend_type`, `initialize`, health, streaming) |
| Auto-load connectors | `src/connectors/__init__.py` imports packages under `src/connectors/` (skips `base`, `mixins`, `_`, etc.) |
| Registration | `backend_registry.register_backend("<id>", Factory)` at module import time |
| Instantiation | `BackendFactory.create_backend` → `get_backend_factory` + `(httpx_client, config, translation_service)` |
| Init kwargs | `BackendFactory.ensure_backend` builds `init_config` from `BackendConfig` (`api_key`, `api_url` → `api_base_url`, `extra`, …) then `initialization_strategy_registry.get_strategy(connector_type).augment_init_config` |
| OpenAI-compatible reference | `OpenAIConnector` in `src/connectors/openai.py` (base URL, `/models` discovery in `initialize`, Bearer auth, streaming) |
| Thin OpenAI-like backends | `ZenmuxConnector` (`src/connectors/zenmux.py`): subclass `OpenAIConnector`, set `backend_type`, default `api_base_url`, optional env API key in `initialize`, `register_backend` |
| Richer variant | `OpenRouterBackend` extends `OpenAIConnector` with extra headers/stream timeouts (`src/connectors/openrouter.py`) |
| Init strategies (optional) | `src/connectors/strategies/*.py` — only `openrouter`, `gemini`, `anthropic`, `example_backend`; others use `DefaultInitializationStrategy` (no-op augment) |
| Config model | `BackendConfig` / `BackendSettings` in `src/core/config/models/backends.py` — `api_key`, `api_url`, `models`, `timeout`, `extra`, … |
| Env fallback (limited) | `BackendFactory.ensure_backend` only auto-fills env keys for `openai` and `minimax` when `backend_config is None`; backends like Zenmux use connector-local `os.getenv` in `initialize` |
| Completion / capture / failover | `BackendCompletionFlow` and collaborators (`src/core/services/backend_completion_flow/`) — backend-agnostic once a concrete `LLMBackend` is used |
| User docs pattern | `docs/user_guide/backends/*.md` + table in `docs/user_guide/backends/overview.md` |

### 1.2 Conventions

- **Naming**: Backend ID is kebab-case string matching YAML key under `backends:` (e.g. `zenmux`, `openrouter`).
- **Tests**: Mirror structure under `tests/`; new connectors typically get unit tests and may reuse OpenAI connector test patterns.
- **No Nvidia artifacts today**: No matches for `nvidia` / `NVIDIA` under `src/connectors/`, `config/schemas/`, or backend docs.

---

## 2. Requirements feasibility and gaps

### 2.1 Requirement-to-asset map

| Req | Need | Asset status | Gap / constraint |
|-----|------|--------------|------------------|
| **1** Stable backend ID + registry + not advertised when unconfigured | New registered type; init only when configured | `backend_registry`, `BackendFactory`, backend stage wiring | **Missing**: `nvidia` (or chosen ID) module + `register_backend`. **Constraint**: “unconfigured” behavior must match existing semantics (no key → skip model list / health behavior like OpenAI parent; verify operator expectations vs Req 2 “predictable failure”). |
| **2** Config + credentials via normal surfaces | `BackendConfig`, YAML, ENV, CLI precedence | `BackendConfig`, loader, semantic validation | **Missing**: Example YAML + documented env var(s); optional **Unknown**: whether strict fail-fast at startup is required for missing key when backend block exists (today OpenAI-style init often logs and continues). |
| **3** Chat completions, streaming, correlation | OpenAI-shaped HTTP + streaming | `OpenAIConnector`, shared httpx client | **Missing**: Nvidia connector. **Research**: hosted Nvidia NIM docs describe OpenAI-compatible `POST /v1/chat/completions` (e.g. `integrate.api.nvidia.com`); self-hosted NIM may use another base URL — design must allow `api_url` override. **Unknown**: parity of `GET /v1/models` for dynamic model lists (parent `initialize` calls it). |
| **4** Errors, failover, usage | Shared completion + error mapping | `LLMProxyError` hierarchy, streaming error helpers | **Partial**: Works if responses resemble OpenAI. **Unknown**: Non-OpenAI error JSON or status codes may need mapping. Usage/token fields in responses — verify against Nvidia payloads for accounting parity. |
| **5** Wire capture + structured logs | Global capture hooks | Existing capture pipeline | **Constraint**: Should work without Nvidia-specific code if routing goes through standard backend execution; verify `backend_type` label after instance rename in `ensure_backend`. |
| **6** Documentation | Backend guide + overview row | `docs/user_guide/backends/` | **Missing**: `nvidia.md` (or similar) + `overview.md` table + env snippet. |

### 2.2 Non-functional notes

- **Performance / streaming**: Inherit from `OpenAIConnector` path; risk is vendor latency, not proxy architecture.
- **Security**: Reuse existing redaction; no new secret surfaces if only API key + URL.

### 2.3 Complexity signals

- **Integration**: External HTTP API (familiar pattern).
- **Risk concentration**: Vendor response shapes, model discovery endpoint, and usage metadata for accounting.

---

## 3. Implementation approach options

### Option A: Extend existing stack — `OpenAIConnector` subclass (recommended baseline)

**What**: Add `src/connectors/nvidia.py` (name TBD) subclassing `OpenAIConnector`, set `backend_type`, default `api_base_url` to documented hosted Nvidia OpenAI-compatible root (design confirms exact default), optional `NVIDIA_API_KEY` (or agreed env name) in `initialize` like Zenmux, `register_backend`.

**Files likely touched**: New connector module; `docs/user_guide/backends/nvidia.md`; `docs/user_guide/backends/overview.md`; `config/config.example.yaml` commented block; tests under `tests/unit` (and integration if needed).

**Trade-offs**: Minimal new code; reuses streaming, translation, and completion flow. **Risk**: Parent assumes `/v1/models` for discovery — may need override if Nvidia endpoint differs (static `models:` in YAML or overridden `initialize`).

### Option B: New `LLMBackend` implementation (custom HTTP)

**What**: Implement provider-specific client without inheriting `OpenAIConnector`.

**When**: Only if Nvidia API diverges materially from OpenAI chat completions + SSE streaming.

**Trade-offs**: Maximum control; **high** duplication and maintenance vs Option A.

### Option C: Hybrid (subclass + initialization strategy)

**What**: Same as A, plus `src/connectors/strategies/nvidia.py` registering defaults (`api_base_url`, optional `key_name` for env discovery in factory if extended).

**When**: If you want `ensure_backend` env fallback centralized like `openai`/`minimax` instead of connector-local `os.getenv`.

**Trade-offs**: Aligns with factory-centric env mapping; extra file and registry wiring.

---

## 4. Effort, risk, and design-phase recommendations

| Label | Value | Justification |
|-------|--------|----------------|
| **Effort** | **S–M** (thin connector + docs + tests) | Clone of Zenmux/OpenRouter patterns; no new architecture. Widen to **M** if model discovery or usage parsing needs custom work. |
| **Risk** | **Medium** | Depends on external API stability and subtle differences (models listing, error bodies, usage fields). |

**Recommendations for design**:

1. **Confirm product scope**: Hosted `integrate.api.nvidia.com` vs self-hosted NIM vs both; single default base URL with `backends.nvidia.api_url` override.
2. **Decide model discovery**: Rely on `GET /v1/models`, static `models:` list, or hybrid fallback.
3. **Choose Option A** unless research shows non–OpenAI-compatible protocol → then B for affected paths only.
4. **Align failure semantics** with Req 2: document whether missing API key with an `nvidia:` config block should hard-fail startup or behave like current OpenAI connector (warning + empty model list).
5. **Accounting**: Trace one successful non-stream and stream response in design/research to map token/usage fields.

---

## 5. Research needed (defer detail to design / `research.md`)

1. **Canonical base URL(s)** and path prefix for target Nvidia offering (hosted vs on-prem).
2. **Models API**: existence and shape of OpenAI-compatible `GET /v1/models` (or alternative catalog API).
3. **Authentication**: Bearer-only vs additional headers (e.g. org/project).
4. **Streaming**: SSE chunk format compatibility with existing `OpenAIConnector` streaming path.
5. **Rate limits / error payloads**: Mapping to `BackendError` / `AuthenticationError` and retry behavior.
6. **Usage / token reporting** fields in responses for usage accounting parity (Req 4.3).

---

## 6. Output checklist (self-verify)

- [x] Requirement-to-asset map with gaps (Missing / Unknown / Constraint)
- [x] Options A / B / C with trade-offs
- [x] Effort (S–M) and Risk (Medium) with short justification
- [x] Design-phase recommendations and research items
