# Technology Stack

**Analysis Date:** 2026-04-04

## Languages

**Primary:**
- Python 3.10+ - Core proxy runtime and all application logic in `src/` with packaging metadata in `pyproject.toml`.

**Secondary:**
- YAML (version not pinned) - Runtime configuration and backend definitions in `config/config.example.yaml`, `config/sso_auth.example.yaml`, and `config/backends/**/*.yaml`.
- Markdown - Operational and feature documentation in `README.md` and `docs/user_guide/**/*.md`.

## Runtime

**Environment:**
- CPython >=3.10 (`requires-python = ">=3.10"`) in `pyproject.toml`.
- ASGI runtime with FastAPI + Uvicorn (`fastapi`, `uvicorn[standard]`) declared in `pyproject.toml` and used in `src/core/cli_support/server_lifecycle_manager.py`.

**Package Manager:**
- pip/setuptools workflow (`build-system` uses `setuptools.build_meta`) in `pyproject.toml`.
- Lockfile: missing (no `poetry.lock`, `Pipfile.lock`, or `uv.lock` detected at repo root).

## Frameworks

**Core:**
- FastAPI (version unpinned) - HTTP API layer and routing, imported in `src/core/cli.py` and started through `src/core/cli_support/server_lifecycle_manager.py`.
- Pydantic v2 (`pydantic>=2`) - Configuration/domain validation models in `src/core/config/models/**/*.py`.
- Typer (dependency declared) - CLI support package in `pyproject.toml`; argparse-based entrypoint is implemented in `src/core/cli.py` and `src/core/cli_support/argument_parser_builder.py`.

**Testing:**
- Pytest 8.x toolchain (`pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-xdist`, `hypothesis`) configured under `[tool.pytest.ini_options]` in `pyproject.toml` and executed in `.github/workflows/ci.yml`.

**Build/Dev:**
- Ruff (`ruff==0.5.6`) and Black (`black==24.8.0`) configured in `pyproject.toml`.
- Mypy (`mypy==1.10.0`) configured in `pyproject.toml`.
- Pre-commit pipeline present in `.pre-commit-config.yaml`.

## Key Dependencies

**Critical:**
- `httpx[http2]` - Outbound HTTP client for provider connectors in `src/connectors/openai.py`, `src/connectors/openrouter.py`, and `src/connectors/nvidia.py`.
- `openai==1.84.0` - OpenAI-compatible backend integration dependency declared in `pyproject.toml` and used by connectors in `src/connectors/`.
- `google-genai` and `google-auth>=2.27.0` - Gemini/GCP integrations declared in `pyproject.toml` and configured via env handling in `src/core/config/env/from_env_part1a.py`.
- `anthropic` - Anthropic backend integration declared in `pyproject.toml` and implemented in `src/connectors/anthropic.py`.
- `authlib>=1.3.0` - OAuth/SSO auth support declared in `pyproject.toml` and wired through `src/core/auth/sso/`.

**Infrastructure:**
- `sqlmodel>=0.0.22` + `alembic>=1.13.0` - SQL-backed persistence components in `src/core/database/` with migration config in `alembic.ini`.
- `aiosqlite>=0.19.0` - Async SQLite storage used in `src/core/auth/sso/database.py` and `src/core/memory/sqlite_repository.py`.
- `structlog` - Structured logging dependency declared in `pyproject.toml` with logging configuration flow in `src/core/cli_support/logging_configurator.py`.
- `cbor2>=5.6.0` - Byte-level capture serialization used for wire capture features referenced in `README.md` and logging config (`cbor_capture_dir`) in `config/config.example.yaml`.

## Configuration

**Environment:**
- Environment variables are first-class config inputs through `src/core/config/env/from_env_part1a.py` and `src/core/config/env/from_env_part3.py`.
- API/provider settings are merged from env into backend config (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `ZAI_API_KEY`, `NVIDIA_API_KEY`, `KIMI_API_KEY`, `MINIMAX_API_KEY`, `INTERNAI_API_KEY*`) in `src/core/config/env/from_env_part3.py`.
- Example config baseline is `config/config.example.yaml`; SSO-focused baseline is `config/sso_auth.example.yaml`.

**Build:**
- Packaging/build metadata: `pyproject.toml` and `setup.py`.
- App config schema and validation assets: `config/schemas/app_config.schema.yaml` and other `config/schemas/*.yaml` files.
- CI build/test automation: `.github/workflows/ci.yml`.

## Platform Requirements

**Development:**
- Python 3.10 runtime in local/CI (`pyproject.toml`, `.github/workflows/ci.yml`).
- Virtual environment workflow documented in `README.md`.
- Filesystem write access for runtime artifacts under `var/` (e.g., `./var/memory.sqlite3`, `./var/sso_auth.db`, logs/captures paths) configured in `config/config.example.yaml`.

**Production:**
- ASGI server process (`uvicorn.run`) managed by `src/core/cli_support/server_lifecycle_manager.py`.
- Deployment target: self-hosted process/container on any OS with Python 3.10+ (no managed platform binding detected in repository configs).
- CI platform detected: GitHub Actions (`.github/workflows/ci.yml`); production CD pipeline definition is not detected.

---

*Stack analysis: 2026-04-04*
