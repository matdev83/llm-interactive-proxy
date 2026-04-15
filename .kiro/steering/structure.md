# Project Structure (Steering)

## Mental Model

Treat the repository as a modular proxy platform with four primary zones:

1. **Core runtime and orchestration** (`src/core/`)
2. **Provider adapters** (`src/connectors/`)
3. **Support subsystems and legacy/top-level modules** (`src/*`)
4. **Operational surfaces** (`config/`, `tests/`, `docs/`, `scripts/`, `dev/`, `var/`)

The architecture favors staged startup, DI-managed seams, and transport-neutral
contracts where possible.

## Organization Patterns

### 1. Core runtime (`src/core/`)

`src/core/` is the primary home for stable business/runtime behavior:

- `app/`: FastAPI composition (controllers, middleware wiring, staged startup)
- `services/`: orchestration-heavy runtime services
- `domain/`: protocol-neutral models and envelopes
- `interfaces/`: DI/test seams (`I*` contracts)
- `ports/` + `adapters/`: boundary contracts and translation helpers
- `transport/fastapi/`: framework-specific mapping to HTTP/SSE/WebSocket behavior
- `config/`: typed config loading/validation and precedence resolution
- `auth/`, `security/`, `memory/`, `database/`: focused capability areas

### 2. Backend adapters (`src/connectors/`)

Connector modules implement provider-specific behavior behind shared backend contracts and protocols.

**Two extension patterns coexist** (see `tech.md` for details):

- **In-repo connectors** under `src/connectors/` (first-party, always available)
- **External plugin connectors** discovered via entry points (`llm_proxy_backends`)
  using `src/core/plugin_api.py` and `src/core/services/backend_plugin_discovery.py`

**Key boundary rule**: Core must not depend on plugin-specific names, private attributes, or distribution details. Classification and execution must be driven by `BackendCapabilityDescriptor` and explicit protocols (`ITokenRefresher`, etc.). The oauth-connectors-plugin-architecture work formalized this boundary.

### 3. Top-level subsystem packages (`src/`)

Not all active code sits under `src/core/`. Important packages outside core include:

- `src/codebuff/` (WebSocket/agent-oriented protocol support)
- `src/loop_detection/` and `src/tool_call_loop/` (loop/tool lifecycle subsystems)
- `src/services/` (cross-cutting services that are not fully migrated)
- `src/resources/` (embedded prompt/resource artifacts)

When touching top-level modules, prefer moving new shared logic into `src/core/`
instead of deepening legacy coupling.

### 4. Operational and support surfaces

- `config/`: runtime YAML templates, backend definitions, schemas, prompt assets
- `tests/`: layered test suites (`unit`, `integration`, `property`, `regression`, etc.)
- `docs/`: user and development guides
- `scripts/`: end-user operational tooling
- `dev/scripts/`: development and maintenance tooling
- `var/`: runtime artifacts (logs, captures, state, local DB files)

## Startup Lifecycle Pattern

Source of truth: `src/core/app/stages/application_stages.py`

Default sequence:

1. Infrastructure
2. Core services
3. Steering/safety wiring
4. Backend wiring
5. Health checks
6. Command wiring
7. Request processing wiring
8. Controller/route wiring

Implication: initialization changes should usually be made in stage modules, not in
ad-hoc startup hooks.

## Where to Change Code (By Intent)

- **Frontend/API behavior**: `src/core/app/controllers/` and transport adapters
- **Core request orchestration**: `src/core/services/request_processor_service.py` +
  internal contracts under `src/core/interfaces/`
- **Backend routing/failover behavior**: `src/core/services/backend_*` and
  `src/core/services/backend_completion_flow/`
- **Connector behavior**: `src/connectors/` (or external plugin package)
- **Config semantics**: `src/core/config/` + related CLI applicators and schemas
- **Safety/auth policy**: `src/core/security/`, `src/core/auth/`, selected services
- **Wire capture/correlation behavior**: capture services in `src/core/services/` and
  simulation tooling under `src/core/simulation/`

## Naming and Import Conventions

- Use absolute imports from `src` for application code
- Naming defaults:
  - module files: `snake_case.py`
  - classes/types: `PascalCase`
  - functions/variables: `snake_case`
  - interfaces: `I*` prefix
- Keep transport/framework-specific symbols out of domain contracts when avoidable

## Structural Guardrails

The oauth-connectors-plugin-architecture work and current architectural priorities reinforce these structure-level rules:

- Core proxy behavior must stay insulated from optional/non-core features (especially extracted OAuth plugins)
- Connector-specific enhancements and name-based heuristics must not leak into core contracts
- Use capability metadata (`BackendCapabilityDescriptor`) and explicit protocols instead of string matching or duck-typing
- Streaming and non-streaming paths should converge where practical
- Session/user isolation boundaries should be explicit and testable
- Plugin API surface (`plugin_api.py`) is the only stable contract for external packages

---

_Updated: 2025-12-27_
_Reason: Link structure map to TDD/testing steering_

_Updated: 2026-01-01_
_Reason: Reflect ports/adapters split introduced by refactors_

_Updated: 2026-04-06_
_Reason: Sync with plugin extension pattern, current top-level subsystem layout, and brownfield structural priorities_

_Updated: 2026-04-15_
_Reason: Incorporate oauth-connectors-plugin-architecture lessons — capability-driven classification, protocol boundaries (`ITokenRefresher`), prohibition on name-based heuristics in core, and plugin API surface rules_
