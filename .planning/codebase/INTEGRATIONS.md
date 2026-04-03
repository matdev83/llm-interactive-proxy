# External Integrations

**Analysis Date:** 2026-04-04

## APIs & External Services

**LLM Provider APIs:**
- OpenAI - Primary OpenAI-compatible backend routing.
  - SDK/Client: `openai==1.84.0` in `pyproject.toml`; connector logic in `src/connectors/openai.py`.
  - Auth: `OPENAI_API_KEY` handled in `src/core/config/env/from_env_part3.py`.
- Anthropic - Native Anthropic backend routing.
  - SDK/Client: `anthropic` in `pyproject.toml`; connector in `src/connectors/anthropic.py`.
  - Auth: `ANTHROPIC_API_KEY` handled in `src/core/config/env/from_env_part3.py`.
- Google Gemini - Gemini backend and Google Cloud project-based integration.
  - SDK/Client: `google-genai`, `google-auth` in `pyproject.toml`; connectors in `src/connectors/gemini.py` and `src/connectors/gemini_cloud_project.py`.
  - Auth: `GEMINI_API_KEY`, plus `GOOGLE_CLOUD_PROJECT`/`GCP_PROJECT_ID` in `src/core/config/env/from_env_part1a.py` and `src/core/config/env/from_env_part3.py`.
- OpenRouter - Multi-provider broker backend.
  - SDK/Client: OpenAI-compatible connector in `src/connectors/openrouter.py`.
  - Auth: `OPENROUTER_API_KEY` in `src/core/config/env/from_env_part3.py`.
- Nvidia NIM - OpenAI-compatible Nvidia integration endpoint.
  - SDK/Client: `src/connectors/nvidia.py` (`NVIDIA_DEFAULT_BASE_URL = https://integrate.api.nvidia.com/v1`).
  - Auth: `NVIDIA_API_KEY` fallback in `src/connectors/nvidia.py`.
- ZAI / Zhipu, Kimi, MiniMax, InternLM, ZenMux - Additional vendor backends.
  - SDK/Client: connectors in `src/connectors/zai.py`, `src/connectors/zai_coding_plan.py`, `src/connectors/kimi_code.py`, `src/connectors/minimax.py`, `src/connectors/internlm.py`, `src/connectors/zenmux.py`.
  - Auth: `ZAI_API_KEY`, `KIMI_API_KEY`, `MINIMAX_API_KEY`, `INTERNAI_API_KEY` (+ numbered variants), `ZENMUX_API_KEY` in `src/core/config/env/from_env_part3.py`.

**Identity/Captcha Services:**
- OAuth/OIDC Identity Providers (Google, Microsoft, GitHub, LinkedIn, AWS IAM Identity Center) - Browser-based SSO login flow.
  - SDK/Client: `authlib` dependency in `pyproject.toml`; SSO implementation in `src/core/auth/sso/`.
  - Auth: Provider `client_id`/`client_secret` in `config/sso_auth.example.yaml` and `src/core/auth/sso/config.py`.
- Cloudflare Turnstile - Optional CAPTCHA verification for SSO form.
  - SDK/Client: HTTP verification config in `src/core/config/env/from_env_part3.py` and `src/core/auth/sso/config.py`.
  - Auth: `SSO_CAPTCHA_SITE_KEY`, `SSO_CAPTCHA_SECRET_KEY`, `SSO_CAPTCHA_VERIFY_URL` in `src/core/config/env/from_env_part3.py`.

**Registry/Metadata Service:**
- models.dev registry - External model metadata ingestion.
  - SDK/Client: model catalog updater services in `src/core/services/model_catalog_updater.py` and config model `src/core/config/models/misc.py`.
  - Auth: No auth variable detected; URL configured by `model_registry.url` / `--model-registry-url` in `config/config.example.yaml` and `src/core/cli_support/argument_parser_builder.py`.

## Data Storage

**Databases:**
- SQLite (multiple local databases).
  - Connection: file-path configuration via `memory.database_path` (`./var/memory.sqlite3`) and `sso.database_path` (`./var/sso_auth.db`) in `config/config.example.yaml`; `MEMORY_DATABASE_PATH` and `SSO_DATABASE_PATH` in env loaders (`src/core/cli_support/applicators/memory_applicator.py`, `src/core/config/env/from_env_part3.py`).
  - Client: `aiosqlite` repositories in `src/core/memory/sqlite_repository.py` and `src/core/auth/sso/database.py`; `sqlmodel` engine/repositories in `src/core/database/engine.py` and `src/core/database/repositories/`.
- SQLite (state persistence service).
  - Connection: `var/state/b2bua_continuity.sqlite3` default path in `src/core/services/b2bua_mapping_store_service.py`.
  - Client: standard `sqlite3` in `src/core/services/b2bua_mapping_store_service.py`.

**File Storage:**
- Local filesystem only (no S3/GCS/Azure blob integration detected).
  - Capture/log/state paths configured in `config/config.example.yaml` and written under `var/`.

**Caching:**
- In-process memory caches and local persisted state files; external cache service (Redis/Memcached) not detected.
  - Example persisted counters/state: `var/state/gemini_oauth_request_count.json` and `var/state/test_suite_state.json`.

## Authentication & Identity

**Auth Provider:**
- Custom API-key auth for proxy endpoints.
  - Implementation: API keys from `API_KEYS` and backend-specific env vars in `src/core/config/env/util.py` and `src/core/config/env/from_env_part3.py`; auth middleware and controls under `src/core/app/middleware/` and `src/core/auth/`.
- Optional SSO auth broker.
  - Implementation: `/auth/*` web interface in `src/core/auth/sso/web_interface.py` with provider configuration from `src/core/auth/sso/config.py` and `config/sso_auth.example.yaml`.

## Monitoring & Observability

**Error Tracking:**
- Dedicated external error tracking service (e.g., Sentry) not detected.

**Logs:**
- Python/structured logging with configurable sink and level in `config/config.example.yaml` and `src/core/cli_support/logging_configurator.py`.
- Wire-level CBOR capture output controlled by `logging.cbor_capture_dir` in `config/config.example.yaml` and consumed by tooling described in `README.md`.

## CI/CD & Deployment

**Hosting:**
- Self-hosted ASGI process via Uvicorn (`src/core/cli_support/server_lifecycle_manager.py`); managed cloud deployment target not declared.

**CI Pipeline:**
- GitHub Actions pipeline in `.github/workflows/ci.yml` (tests, boundary checks, Codecov upload).

## Environment Configuration

**Required env vars:**
- Core auth/access: `API_KEYS`, `AUTH_TOKEN`, `DISABLE_AUTH` in `src/core/config/env/from_env_part1a.py` and `src/core/config/env/util.py`.
- Provider credentials/endpoints: `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `ZAI_API_KEY`, `NVIDIA_API_KEY`, `KIMI_API_KEY`, `MINIMAX_API_KEY`, `INTERNAI_API_KEY` (+ numbered variants), and corresponding `*_API_BASE_URL` / `*_TIMEOUT` values in `src/core/config/env/from_env_part3.py`.
- SSO/captcha: `SSO_ENABLED`, `SSO_DATABASE_PATH`, `SSO_AUTH_MODE`, `SSO_AUTH_API_URL`, `SSO_CAPTCHA_*` variables in `src/core/config/env/from_env_part3.py`.

**Secrets location:**
- Environment variables are the primary secret source (`src/core/config/env/*.py`); examples explicitly discourage storing API keys in YAML (`config/config.example.yaml:25` and `config/config.example.yaml:227`).
- Optional provider/token stores on disk are referenced by path (for example `var/gemini_oauth_accounts` in `config/config.example.yaml` and `~/.qwen/oauth_creds.json` in `config/backends/backend-instances/qwen-oauth.default.yaml`).

## Webhooks & Callbacks

**Incoming:**
- OAuth callback endpoint: `/auth/callback` in `src/core/auth/sso/web_interface.py`.
- Diagnostics reactivation endpoint (operational callback-like control): `/v1/diagnostics/backends/{backend_instance}/reactivate` in `src/core/app/controllers/diagnostics_controller.py`.

**Outgoing:**
- OAuth/OIDC and captcha verification callbacks to provider endpoints configured in `src/core/auth/sso/idp_configs.py` and `src/core/config/env/from_env_part3.py` (for example provider authorize/token/userinfo/discovery URLs and Turnstile verify URL).
- General-purpose third-party webhook emitter integration is not detected.

---

*Integration audit: 2026-04-04*
