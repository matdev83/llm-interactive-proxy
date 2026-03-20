# Research and design decisions: Nvidia API backend

**Feature**: `nvidia-api-backend`  
**Discovery scope**: Extension (new connector on existing backend architecture)

---

## Summary

- **Feature**: `nvidia-api-backend`
- **Discovery scope**: Extension
- **Key findings**:
  - Hosted NVIDIA NIM LLM API documents OpenAI-compatible access at base `https://integrate.api.nvidia.com` with `POST /v1/chat/completions`; model catalog aligns with OpenAI-style `GET /v1/models` for discovery.
  - In-repo pattern `ZenmuxConnector` (`OpenAIConnector` subclass + `register_backend` + env API key in `initialize`) matches requirements for `NVIDIA_API_KEY` and minimal core churn.
  - No new DI services or processor stages are required; `BackendFactory`, `BackendCompletionFlow`, and wire capture treat backends uniformly once registered.

---

## Research log

### Existing codebase analysis

- **Components reviewed**: `src/connectors/base.py`, `src/connectors/openai.py`, `src/connectors/zenmux.py`, `src/connectors/__init__.py`, `src/core/services/backend_factory.py`, `src/core/services/backend_registry.py`, `src/core/config/models/backends.py`, tests under `tests/unit/connectors/test_zenmux_connector.py`.
- **Patterns identified**: Import-time `backend_registry.register_backend`; factory constructs `(httpx.AsyncClient, AppConfig, TranslationService)`; `BackendConfig.api_key` and `api_url` map to `initialize(api_key=..., api_base_url=...)`; optional env fallback inside `initialize` when YAML key absent; `VENDOR_PREFIX = None` for multi-vendor model IDs on gateway-style APIs.
- **Implications**: Nvidia connector should subclass `OpenAIConnector`, set default base URL to `https://integrate.api.nvidia.com/v1`, apply `NVIDIA_API_KEY` in `initialize` when `kwargs` lack `api_key`, and register as backend type `nvidia`.

### NVIDIA hosted API shape

- **Context**: Confirm compatibility with `OpenAIConnector` HTTP and streaming paths.
- **Sources consulted**: [NVIDIA NIM LLM APIs](https://docs.api.nvidia.com/nim/reference/llm-apis) (base URL `https://integrate.api.nvidia.com`, `POST /v1/chat/completions`); [Models reference](https://docs.api.nvidia.com/nim/reference/models-1) for list/catalog patterns.
- **Findings**: Documented surface is OpenAI-compatible chat completions on the hosted integrator; models use vendor-prefixed ids (e.g. `meta/llama3-70b`). Listing endpoint behavior is compatible with parent `initialize` model fetch when credentials are valid.
- **Implications**: Default implementation reuses parent streaming and non-streaming logic; self-hosted NIM remains addressable via `backends.nvidia.api_url` overriding default base URL.

### Credential precedence vs `BackendFactory`

- **Context**: `BackendFactory.ensure_backend` only auto-injects env API keys for `openai` and `minimax` when `backend_config is None`; Zenmux uses connector-local `os.getenv` in `initialize`.
- **Findings**: YAML-supplied `api_key` is passed through `init_config` and wins over env in Zenmux pattern because `kwargs.get("api_key")` is truthy first.
- **Implications**: Implement `NVIDIA_API_KEY` in `NvidiaConnector.initialize` consistent with Zenmux to satisfy Req 2.4 without expanding `env_key_mapping` (optional follow-up for centralization only).

---

## Architecture pattern evaluation

| Option | Description | Strengths | Risks / limitations |
|--------|-------------|-----------|---------------------|
| OpenAIConnector subclass | New `nvidia` module, register with registry | Reuses streaming, errors, translation, health | Assumes OpenAI-compatible responses; self-hosted quirks need `api_url` + testing |
| Standalone LLMBackend | Custom HTTP client per method | Full control | Duplicates OpenAI path; high maintenance |
| OpenRouter-style strategy module | `initialization_strategy_registry` entry | Central env defaults | Extra file; only justified if factory must inject env without YAML block |

**Selected**: OpenAIConnector subclass (row 1).

---

## Design decisions

### Decision: Backend identifier

- **Context**: Stable `backend:model` prefix and config key.
- **Selected approach**: Register backend type string `nvidia` (lowercase, matches `openai`, `zenmux` conventions).
- **Rationale**: Short, unambiguous, consistent with overview table style.

### Decision: Default API base URL

- **Context**: Hosted vs self-hosted deployments.
- **Selected approach**: Default `https://integrate.api.nvidia.com/v1`; operators override with `backends.nvidia.api_url` for self-hosted NIM or alternate endpoints.
- **Rationale**: Matches official hosted documentation; override preserves enterprise deployments.

### Decision: Model discovery

- **Context**: `OpenAIConnector.initialize` fetches `GET {api_base_url}/models`.
- **Selected approach**: Rely on parent behavior; allow static `models:` list in `BackendConfig` if validation or offline listing is required later.
- **Rationale**: Documented OpenAI-style models listing exists for hosted API; parent already degrades gracefully on failure.

---

## Risks and mitigations

- **Vendor response or usage fields differ slightly from OpenAI** — Mitigation: integration tests against recorded fixtures; verify usage accounting on sample responses during implementation.
- **Self-hosted NIM path or auth headers differ** — Mitigation: document `api_url` and refer to NVIDIA downloadable NIM docs; extend headers only if proven necessary.
- **Missing API key with empty YAML block** — Mitigation: align behavior with comparable backends (log, skip model list); document that routing to `nvidia` without credentials yields predictable errors at request time.

---

## References

- [NVIDIA NIM LLM APIs](https://docs.api.nvidia.com/nim/reference/llm-apis)
- [NVIDIA API models](https://docs.api.nvidia.com/nim/reference/models-1)
- Project steering: `.kiro/steering/structure.md`, `.kiro/steering/tech.md`
- Gap analysis: `.kiro/specs/nvidia-api-backend/gap-analysis.md`
