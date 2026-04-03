# Architecture

**Analysis Date:** 2026-04-04

## Pattern Overview

**Overall:** Service-oriented modular monolith with staged startup and dependency injection.

**Key Characteristics:**
- Build the runtime through explicit initialization stages in `src/core/app/stages/` and execute them in dependency order via `ApplicationBuilder` in `src/core/app/application_builder.py`.
- Resolve runtime dependencies through the in-repo DI container in `src/core/di/container.py` and registrar orchestration in `src/core/di/services.py` and `src/core/di/registrations/`.
- Keep transport/protocol surfaces in FastAPI controllers under `src/core/app/controllers/`, while business orchestration is concentrated in services under `src/core/services/`.

## Layers

**Entry/Bootstrap Layer:**
- Purpose: Parse startup arguments, load config, build app, and run server lifecycle.
- Location: `src/core/cli.py`, `src/core/cli_support/`, `src/anthropic_server.py`.
- Contains: CLI parser/applicators, startup validation, server lifecycle orchestration.
- Depends on: App builder (`src/core/app/application_builder.py`), config (`src/core/config/`), logging/runtime support.
- Used by: Process entry points (`python -m src.core.cli`, Anthropic-specific server startup).

**Application Composition Layer:**
- Purpose: Compose the FastAPI application and wire middleware/routes/lifecycle.
- Location: `src/core/app/application_builder.py`, `src/core/app/stages/`, `src/core/app/middleware_config.py`.
- Contains: Stage registration/execution, middleware registration, route registration, lifespan hooks.
- Depends on: DI service collection/provider, controllers package, transport exception adapters.
- Used by: CLI startup and anthropic server bootstrap.

**Transport Layer (HTTP/API adapters):**
- Purpose: Expose API contracts and map HTTP I/O to internal request/response shapes.
- Location: `src/core/app/controllers/`, `src/core/transport/fastapi/`.
- Contains: Route handlers (`/v1/chat/completions`, `/v1/responses`, `/internal/health`), request/exception/response adapters.
- Depends on: DI-resolved controllers/services (e.g. `RequestProcessor`).
- Used by: External clients targeting OpenAI/Anthropic/Gemini-compatible endpoints.

**Application Services Layer:**
- Purpose: Execute orchestration and policy-heavy workflows.
- Location: `src/core/services/` (notably `request_processor_service.py`, backend routing/validation/health submodules).
- Contains: Request orchestration, backend preparation/execution, command processing, model routing/replacement, streaming, usage, health subsystems.
- Depends on: Domain models/interfaces, connectors, repositories, DI bindings.
- Used by: Controllers and stage-registered pipeline components.

**Domain/Contracts Layer:**
- Purpose: Define core entities, request context, translation contracts, and domain rules.
- Location: `src/core/domain/`, `src/core/interfaces/`, `src/core/ports/`.
- Contains: Chat/response models, session identity/context, capability and usage models, service interfaces, normalization/streaming contracts.
- Depends on: Minimal utility modules; avoids direct HTTP framework coupling.
- Used by: Services, transport adapters, connectors.

**Infrastructure/Integration Layer:**
- Purpose: Handle external provider communication and foundational runtime resources.
- Location: `src/connectors/`, `src/core/app/stages/infrastructure.py`, `src/core/database/`, `src/core/services/health/`.
- Contains: Backend connector implementations, shared `httpx.AsyncClient`, endpoint health checkers, persistence engines/repositories.
- Depends on: Provider SDK protocols, network I/O, database drivers.
- Used by: Backend services and runtime lifecycle hooks.

## Data Flow

**Primary Chat Request Flow:**

1. Incoming HTTP request hits FastAPI route registration in `src/core/app/controllers/__init__.py` (for example `@app.post("/v1/chat/completions")`).
2. Route dependency resolves controller from DI-backed app state (`get_chat_controller_if_available`), then delegates to controller method in `src/core/app/controllers/chat_controller.py`.
3. Controller delegates orchestration to request processing pipeline (`RequestProcessor` in `src/core/services/request_processor_service.py`) via interfaces wired in `src/core/app/stages/processor.py`.
4. Request processor coordinates command handling, session enrichment, request transforms, backend preparation, and backend execution using `ICommandHandler`, `ISessionEnricher`, `IRequestTransformPipeline`, `IBackendPreparer`, and `IBackendExecutor`.
5. Backend services route to provider connectors from `src/connectors/` and return normalized responses through response/stream formatting services and FastAPI adapters.

**Application Startup Flow:**

1. CLI bootstrap in `src/core/cli.py` parses args and builds config (`load_config`/`apply_cli_args`).
2. `build_app_async` in `src/core/app/application_builder.py` discovers backends, validates semantic config, validates stages, and executes stages in topologically sorted order.
3. Stage sequence composes services (`Infrastructure -> CoreServices -> Steering -> Backend -> Command -> Processor -> Controller`; `DefaultApplicationStages` also includes `HealthCheckStage` in `src/core/app/stages/application_stages.py`).
4. Builder instantiates FastAPI app, configures middleware (`src/core/app/middleware_config.py`), registers routes (`src/core/app/controllers/__init__.py`), exception handlers, and lifespan startup/shutdown hooks.

**State Management:**
- Use service-centric state with DI singletons/scoped/transient lifetimes (`ServiceLifetime` in `src/core/interfaces/di_interface.py` and implementation in `src/core/di/container.py`).
- Keep runtime app/service references in `app.state` (`service_provider`, `app_config`) in `src/core/app/application_builder.py`.
- Manage session/conversation continuity through session services and repositories (`src/core/services/session_service_impl.py`, `src/core/repositories/in_memory_session_repository.py`, domain session models in `src/core/domain/session.py`).

## Key Abstractions

**InitializationStage:**
- Purpose: Standard contract for startup units with dependencies and validation.
- Examples: `src/core/app/stages/base.py`, `src/core/app/stages/infrastructure.py`, `src/core/app/stages/processor.py`.
- Pattern: Dependency-declared staged initialization with topological sort.

**ServiceCollection / ServiceProvider:**
- Purpose: Register and resolve application services with lifetimes and factory-based wiring.
- Examples: `src/core/di/container.py`, `src/core/di/services.py`.
- Pattern: Constructor/factory DI container with singleton/scoped/transient semantics.

**Controller + Processor split:**
- Purpose: Keep transport thin and move orchestration into dedicated services.
- Examples: `src/core/app/controllers/__init__.py`, `src/core/app/controllers/chat_controller.py`, `src/core/services/request_processor_service.py`.
- Pattern: HTTP adapter/controller delegates to service pipeline.

**Connector abstraction:**
- Purpose: Encapsulate provider-specific protocol differences behind backend service orchestration.
- Examples: `src/connectors/openai.py`, `src/connectors/anthropic.py`, `src/connectors/gemini.py`, `src/connectors/openrouter.py`.
- Pattern: Adapter/connector family with registry/discovery and backend routing services.

## Entry Points

**Primary CLI Entry Point:**
- Location: `src/core/cli.py`.
- Triggers: `python -m src.core.cli`.
- Responsibilities: Parse CLI/config, validate mode/runtime constraints, invoke server lifecycle manager and app builder.

**App Builder Entry Point:**
- Location: `src/core/app/application_builder.py` (`build_app_async`).
- Triggers: CLI startup and dedicated server wrappers.
- Responsibilities: Backend discovery, semantic validation, staged service initialization, FastAPI app assembly.

**Anthropic-Dedicated Entry Point:**
- Location: `src/anthropic_server.py`.
- Triggers: Anthropic-specific process startup.
- Responsibilities: Build/reuse base services and expose Anthropic-focused route surface.

## Error Handling

**Strategy:** Layered handling: domain/service exceptions are normalized at transport boundaries, with defensive fallbacks during startup and service resolution.

**Patterns:**
- Use centralized FastAPI exception registration in `src/core/transport/fastapi/exception_adapters.py` from builder `_register_exception_handlers`.
- Map controller dependency failures to HTTP 503/500 in `src/core/app/controllers/__init__.py` when DI services are unavailable.
- Guard stage execution with fail-fast `RuntimeError` wrapping and cleanup in `src/core/app/application_builder.py`.

## Cross-Cutting Concerns

**Logging:** Structured, pervasive logging through stage execution, middleware setup, controller resolution, and startup/lifecycle hooks (examples in `src/core/app/application_builder.py`, `src/core/app/stages/*.py`, `src/core/app/middleware_config.py`).

**Validation:** Multi-layer validation via CLI arg validator (`src/core/cli_support/cli_args_validator.py`), semantic config validators (`src/core/config/semantic_validation.py`), and stage-level `validate()` methods.

**Authentication:** Auth configured as middleware in `src/core/app/middleware_config.py` (`APIKeyMiddleware`, `AuthMiddleware`, SSO auth middleware path), with access-mode-aware behavior configured from `AppConfig`.

---

*Architecture analysis: 2026-04-04*
