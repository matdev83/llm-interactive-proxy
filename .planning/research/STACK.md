# Technology Stack

**Project:** LLM Interactive Proxy — Universal LLM Gateway / Agent Control Plane
**Researched:** 2026-04-04
**Scope:** Subsequent milestone — hardening + expansion (brownfield)

---

## Executive Decisions

This is a brownfield project with a stable, well-validated core. The stack below is organized as **KEEP** (current choices that remain strong), **ADOPT** (new additions worth integrating in this milestone), and **AVOID** (alternatives that are wrong for this codebase).

---

## KEEP — Current Choices That Remain Strong

### Core Framework & Runtime

| Technology | Current State | Verdict | Why |
|------------|--------------|---------|-----|
| **FastAPI** | 0.135.3 (Apr 2026) — very active release cadence | KEEP | 135+ releases since 2019, actively maintained through 2026. Built-in SSE tutorial, WebSocket support, and OpenAPI auto-gen all align with the proxy's frontend surfaces. |
| **uvicorn[standard]** | uvloop + httptools via `[standard]` extra | KEEP | Benchmark score 92/100 in Context7. `--workers` support for production scaling. The `standard` extra pulls in `uvloop` and `httptools` — both optimal for Linux; falls back gracefully on Windows (ProactorEventLoop). |
| **httpx[http2]** | 0.28.1 (Dec 2024), actively maintained | KEEP | The standard async HTTP client for Python. HTTP/2 support is essential for backends like OpenAI and Anthropic that use HTTP/2 servers. Recent additions: zstd decoding, proxy mounts, HTTPS proxies. |
| **Pydantic v2** | Pydantic 2.12 docs available | KEEP | Benchmark score 85-87/100 across Context7 libraries. The entire request/response envelope system, config schemas, and domain models are built on it. No viable replacement worth the migration cost. |
| **SQLModel + Alembic** | SQLModel 0.0.24, Alembic ≥1.13 | KEEP | SQLModel 0.0.24 is the latest stable. Combines SQLAlchemy 2.0 core with Pydantic v2 models — exactly the sweet spot for a FastAPI + Pydantic codebase. Alembic migrations are working. |
| **structlog** | hynek/structlog — benchmark 92/100 | KEEP | Best-in-class Python structured logging. JSON output, JSON-logformatters for GCP, and native async support. The project already uses it effectively. |
| **authlib** | ≥1.3.0 in dependencies | KEEP | Comprehensive OAuth/SAML/OIDC library. The project already uses it for SSO flows. Superior to httpx-oauth for multi-provider SSO with its built-in starlette/fastapi integration. |
| **cbor2** | ≥5.6.0 | KEEP | Byte-precise wire captures are core product value. CBOR is the established capture format; replacing it would invalidate the debugging tooling (`scripts/inspect_cbor_capture.py`). |

### Testing & Quality

| Technology | Current State | Verdict | Why |
|------------|--------------|---------|-----|
| **pytest** | 8.3.2 + xdist (loadfile) + testmon | KEEP | 13,195 tests passing. The test infrastructure is mature with custom markers, TDD patterns, and "tests as executable specifications" discipline. |
| **pytest-asyncio** | 0.23.7 with `asyncio_mode = "auto"` | KEEP | Confirmed correct pattern: auto mode auto-detects async tests/fixtures without manual markers. Context7 docs confirm this is "the recommended default" for asyncio-only projects. |
| **ruff** | 0.5.6, F/E9/I/N/UP/B/SIM/C4/PIE/C90/RUF rules | KEEP | Fast, comprehensive, well-configured. Catch real issues without formatting noise. Consider unpinning from 0.5.6 — Ruff moves fast and the rule set is locked in `pyproject.toml`. |
| **black** | 24.8.0 | KEEP | Formatting is stable. Line length 88 matches ruff config. |
| **mypy** | 1.10.0, `disallow_untyped_defs = true` | KEEP | Type discipline is enforced. Consider adding `pyright` as a secondary checker for faster incremental feedback, but keep mypy as the CI gate. |

### Supporting

| Technology | Verdict | Why |
|------------|---------|-----|
| **tiktoken** | KEEP | OpenAI's tokenizer — needed for token accounting, context window enforcement, and cost tracking. |
| **cachetools** | KEEP | TTL/cached properties for health checks, routing decisions, and rate limit state. |
| **python-dotenv** | KEEP | Local dev convenience for loading `.env` files. Not used for config resolution (CLI > ENV > YAML handles that). |
| **typer + rich** | KEEP | CLI surface with colorful output. Matches the project's developer-experience-first ethos. |
| **websockets** | KEEP (but UPGRADE) | Currently ≥12.0 — pytest already suppresses `websockets.legacy` deprecation warnings (v14+ API shift). Upgrade to ≥14 to use new API and remove deprecation suppressions. |
| **aiostream / anyio patterns** | IMPLICIT KEEP | The project uses `anyio.create_memory_object_stream` patterns for SSE streaming. This is correct and aligns with sse-starlette's design. |

---

## ADOPT — New Additions Worth Integrating

### Observability

| Library | Version | Purpose | Rationale | Confidence |
|---------|---------|---------|-----------|------------|
| **opentelemetry-api + opentelemetry-sdk** | Latest stable | Distributed tracing, metrics, logs | OpenTelemetry is the 2026 standard for vendor-neutral observability. Auto-instrumentation packages exist for FastAPI (`opentelemetry-instrumentation-fastapi`), httpx (`opentelemetry-instrumentation-httpx`), and asyncio. Essential for multi-provider proxy debugging where you need to trace a request across frontend → processor → backend → response. | HIGH |
| **opentelemetry-instrumentation-fastapi** | Latest | Auto-instrument FastAPI routes, middleware | Adds request/response spans with HTTP attributes automatically. Context propagation via W3C TraceContext is built-in. | HIGH |
| **opentelemetry-instrumentation-httpx** | Latest | Auto-instrument outgoing httpx calls | Every backend connector call gets traced — latency, status, error rates per provider. Critical for operational visibility. | HIGH |
| **prometheus-client** | ≥0.20.0 | Prometheus metrics export | Lighter-weight than OpenTelemetry for pure metrics. Supports multi-process mode (via `PROMETHEUS_MULTIPROC_DIR`) for uvicorn workers. Context7 confirms FastAPI mount pattern: `app.mount("/metrics", make_asgi_app())`. | HIGH |

### Protocol & Streaming

| Library | Version | Purpose | Rationale | Confidence |
|---------|---------|---------|-----------|------------|
| **sse-starlette** | ≥3.3.4 (latest: Mar 2026) | Server-Sent Events for FastAPI | Production-ready SSE following W3C spec. 821 GitHub stars, 382 commits. Built-in client disconnect detection, graceful shutdown, memory channels for complex data flows, cooperative shutdown with grace periods. Essential for streaming LLM responses to frontends cleanly. | HIGH |
| **httpx-sse** | ≥0.4.0 (latest: Oct 2025) | Client-side SSE parsing | Parse SSE streams FROM backends (OpenAI, Anthropic, etc. all use SSE for streaming responses). By florimondmanca (encode/httpx contributor). Supports `aconnect_sse` for async. No built-in reconnection — but the proxy already has its own failover/retry logic in `BackendCompletionFlow`. | HIGH |

### Resilience

| Library | Version | Purpose | Rationale | Confidence |
|---------|---------|---------|-----------|------------|
| **stamina** | Latest (by hynek, structlog author) | Structured retry with async support | Async-native retry library with exponential backoff, jitter, and structured logging integration. Works with `@retry` decorator and context managers. Better than ad-hoc retry loops scattered across backend connectors. Complements the existing failover system rather than replacing it. | HIGH |

### Dev Tooling

| Library | Version | Purpose | Rationale | Confidence |
|---------|---------|---------|-----------|------------|
| **pyright** | Latest | Secondary type checker | Faster incremental checks than mypy. Useful as an IDE companion (many agents already use it). Keep mypy as CI gate, add pyright for developer feedback loop. | MEDIUM |
| **pytest-coverage** | Already present (pytest-cov 5.0.0) | Keep and enforce thresholds | Coverage is tracked via Codecov badge. Ensure coverage thresholds don't regress as new connectors and features are added. | HIGH |

### Configuration

| Library | Version | Purpose | Rationale | Confidence |
|---------|---------|---------|-----------|------------|
| **pydantic-settings** | Latest | Optional: structured settings base classes | **Adopt selectively.** The project's custom CLI > ENV > YAML > defaults precedence system is deeply integrated and shouldn't be replaced wholesale. But pydantic-settings can be used for new subsystem config (e.g., OpenTelemetry exporter config, Prometheus settings) where its `BaseSettings` model with env/file sources would reduce boilerplate. | MEDIUM |

---

## AVOID — Wrong Choices for This Codebase

### Framework Swaps

| Alternative | Why Avoid |
|-------------|-----------|
| **Flask / aiohttp / Sanic / Litestar / Starlite** | FastAPI is the dominant choice in 2026 Python async API space. The entire codebase — 8-stage startup, DI container, transport layer, controllers — assumes FastAPI/Starlette. Any swap would be a 6+ month rewrite with zero user-facing benefit. |
| **Django / Django Ninja** | Heavy, ORM-tied, and fundamentally synchronous-first. The proxy is transport-neutral, async-native, and provider-agnostic — Django's batteries-included model works against that. |
| **Litestar** | Interesting architecture (heavily DI-focused), but the ecosystem is smaller, community is narrower, and migration cost is prohibitive for marginal gains. |

### HTTP / Protocol

| Alternative | Why Avoid |
|-------------|-----------|
| **aiohttp** | httpx already covers everything aiohttp does, with better type hints, HTTP/2 support, and a more modern API. No reason to introduce a second HTTP client. |
| **requests + threads** | The proxy is async-native. Introducing a sync HTTP client would block the event loop and undermine the performance characteristics that make this proxy viable. |
| **gRPC** | LLM provider APIs are HTTP/JSON or HTTP/SSE. No provider uses gRPC natively. Adding gRPC support without a use case is gold plating. |

### Task Queue / Background

| Alternative | Why Avoid |
|-------------|-----------|
| **Celery** | Overkill for a process that can use `anyio.create_task_group` for background work. Celery introduces infrastructure complexity (broker, workers, result backend) that the proxy doesn't need. |
| **asyncio.Queue patterns** for complex flows | Prefer `anyio.create_memory_object_stream` — the project already uses this for SSE. It's cleaner, supports pub/sub patterns naturally, and integrates with sse-starlette. |

### ORM / Database

| Alternative | Why Avoid |
|-------------|-----------|
| **SQLAlchemy 2.0 standalone** | SQLModel already wraps SQLAlchemy 2.0 with Pydantic integration. Dropping down to raw SQLAlchemy gains nothing but loses the Pydantic model alignment that keeps FastAPI + DB schemas consistent. |
| **Prisma / Tortoise ORM / Piccolo** | All either less mature, less integrated with Pydantic, or designed for different ecosystems. SQLModel is the right fit for this FastAPI codebase. |
| **Redis** | For health check state, cooldown tracking, and session caching, SQLite (via SQLModel) with `cachetools` is sufficient at current scale. Add Redis only if multi-instance deployment with shared state becomes a real requirement. |

### OAuth / Auth

| Alternative | Why Avoid |
|-------------|-----------|
| **httpx-oauth** | Less comprehensive than authlib. The project already uses authlib successfully for SSO. httpx-oauth is a thin wrapper that doesn't handle the multi-provider OIDC/SAML needs the proxy has. |
| **Auth0 SDK / Okta SDK** | Vendor lock-in. The proxy's value is vendor independence for LLM backends — the same principle should apply to identity providers. authlib is the vendor-neutral choice. |

### Logging / Observability

| Alternative | Why Avoid |
|-------------|-----------|
| **Loguru** | Easier for simple apps, but structlog is more composable, better for production structured output, and already integrated. Loguru's magic (auto-configuration, exception formatting) is at odds with the proxy's explicit, testable architecture. |
| **Sentry SDK as primary observability** | Good for error tracking, but Sentry is an error-aggregation tool, not a structured observability system. Prefer OpenTelemetry for tracing/metrics + Sentry (optional) as an error sink. |

### Type Checking

| Alternative | Why Avoid |
|-------------|-----------|
| **Drop mypy for pyright only** | mypy has broader ecosystem support, more third-party stubs (`types-*` packages), and is the established CI gate in this project. Pyright is a good IDE companion but shouldn't replace mypy. |

---

## Dependency Maintenance Notes

### Pinning Strategy

| Package | Strategy | Reason |
|---------|----------|--------|
| `openai==1.84.0` | **Unpin to `>=1.84.0`** | Exact pin creates unnecessary upgrade friction. The OpenAI SDK is semver-stable. Pin only if a specific version caused a regression worth documenting. |
| `pytest-asyncio==0.23.7` | **Consider unpinning to `>=0.23.7`** | The `asyncio_mode = "auto"` config is stable across versions. Newer versions of pytest-asyncio fix bugs and add features. Test thoroughly before upgrading. |
| `pytest==8.3.2` | **Unpin to `>=8.3.2`** | pytest is very backwards-compatible. Newer point releases fix bugs. |
| `ruff==0.5.6` | **Unpin to `>=0.5.6`** | Ruff moves very fast. The rule set in `pyproject.toml` is locked — Ruff versions just affect which rules are available, not which are enforced. |
| `black==24.8.0` | **Keep pinned or widen to `>=24.8.0`** | Black's formatting output can change between versions, which creates noisy diffs. Pinning is defensible here, but `>=24.8.0` is safe if team agrees. |
| `mypy==1.10.0` | **Keep pinned or widen to `>=1.10.0`** | mypy type inference can change between versions, potentially surfacing new errors. Pinning is safer for CI stability. |

### Known Deprecations to Address

| Deprecation | Where | Mitigation |
|-------------|-------|------------|
| `websockets.legacy` warnings | `pytest` filterwarnings, `websockets.server.WebSocketServerProtocol` | Upgrade websockets to ≥14.0 and migrate to new API. The deprecation suppressions are masking real warnings. |
| `verify` string argument in httpx | httpx 0.28.0+ | If the project passes `verify="path"` or `verify=string` to httpx, migrate to the new SSL API per httpx 0.28.0 docs. |
| `pytest-cov` / pytest-xdist interaction | pytest configuration | Already managed via `--dist=loadfile`. Monitor for conflicts as versions evolve. |

---

## Recommended Additions (Summary Table)

| Layer | Add This | Skip This | Decision |
|-------|----------|-----------|----------|
| Tracing | OpenTelemetry Python | Jaeger client (deprecated), Zipkin | OpenTelemetry is the 2026 standard |
| Metrics | prometheus-client | statsd + custom exporter, InfluxDB client | Prometheus is the universal standard |
| SSE (serve) | sse-starlette ≥3.3.4 | Starlette StreamingResponse (manual SSE format) | sse-starlette handles protocol correctly |
| SSE (consume) | httpx-sse ≥0.4.0 | Manual `text/event-stream` parsing | httpx-sse is the dedicated client library |
| Retry | stamina | tenacity (more complex), ad-hoc retry loops | stamina is simpler, async-native, structured-logging-aware |
| Type checks | Keep mypy + add pyright (optional) | Replace mypy with pyright | mypy is the CI gate; pyright is faster for dev |
| Config | pydantic-settings (selective use) | Replace custom CLI > ENV > YAML system | Custom system is a core product feature |
| WebSocket tests | httpx-ws (if needed) | Manual WebSocket client test code | Cleaner test ergonomics for WS routes |

---

## Sources

- **FastAPI release notes**: fastapi.tiangolo.com/release-notes/ — confirms 0.135.3 as of April 1, 2026 (HIGH)
- **httpx releases**: github.com/encode/httpx/releases — 0.28.1 (Dec 2024), active maintenance (HIGH)
- **sse-starlette**: github.com/sysid/sse-starlette — v3.3.4 (Mar 2026), 821 stars, production-ready (HIGH)
- **httpx-sse**: github.com/florimondmanca/httpx-sse — v0.4.3 (Oct 2025), by encode contributor (HIGH)
- **OpenTelemetry Python**: opentelemetry-python — official OTel SDK for Python (HIGH)
- **prometheus-client**: github.com/prometheus/client_python — FastAPI multi-process mode docs confirmed (HIGH)
- **uvicorn**: github.com/kludex/uvicorn — benchmark 92/100, production docs confirmed (HIGH)
- **pydantic**: pydantic.dev — 2.12 docs, mature ecosystem (HIGH)
- **SQLModel**: sqlmodel.tiangolo.com — latest stable 0.0.24 (HIGH)
- **structlog**: github.com/hynek/structlog — benchmark 92/100, actively maintained (HIGH)
- **stamina**: github.com/hynek/stamina — by hynek (structlog/attrs author), async-native retry (HIGH)
- **pytest-asyncio**: github.com/pytest-dev/pytest-asyncio — auto mode confirmed as recommended default (HIGH)
- **pyproject.toml**: local project file — dependency inventory and tooling config (HIGH)
