# Design Document Template

---
**Purpose**: Provide sufficient detail to ensure implementation consistency across different implementers, preventing interpretation drift.

**Approach**:
- Include essential sections that directly inform implementation decisions
- Omit optional sections unless critical to preventing implementation errors
- Match detail level to feature complexity
- Use diagrams and tables over lengthy prose

**Warning**: Approaching 1000 lines indicates excessive feature complexity that may require design simplification.

**Project Context**: Universal LLM Proxy - FastAPI async service with staged initialization, DI containers, adapter pattern for LLM backends.
---

> Sections may be reordered (e.g., surfacing Requirements Traceability earlier or moving Data Models nearer Architecture) when it improves clarity. Within each section, keep the flow **Summary -> Scope -> Decisions -> Impacts/Risks** so reviewers can scan consistently.

## Overview
2-3 paragraphs max
**Purpose**: This feature delivers [specific value] to [target users].
**Users**: [Target user groups] will utilize this for [specific workflows].
**Impact** (if applicable): Changes the current [system state] by [specific modifications].


### Goals
- Primary objective 1
- Primary objective 2
- Success criteria

### Non-Goals
- Explicitly excluded functionality
- Future considerations outside current scope
- Integration points deferred

## Architecture

> Reference detailed discovery notes in `research.md` only for background; keep design.md self-contained for reviewers by capturing all decisions and contracts here.
> Capture key decisions in text and let diagrams carry structural detail--avoid repeating the same information in prose.

### Existing Architecture Analysis (if applicable)
When modifying existing systems:
- Current architecture patterns and constraints (check `src/core/app/stages/` for initialization order)
- Existing domain boundaries to be respected (interfaces in `src/core/interfaces/`)
- Integration points that must be maintained (connectors in `src/connectors/`)
- Technical debt addressed or worked around

### Architecture Pattern & Boundary Map
**RECOMMENDED**: Include Mermaid diagram showing the chosen architecture pattern and system boundaries (required for complex features, optional for simple additions)

**Architecture Integration**:
- Selected pattern: [name and brief rationale]
- Domain/feature boundaries: [how responsibilities are separated to avoid conflicts]
- Existing patterns preserved: [list key patterns - adapter, DI, staged init, etc.]
- New components rationale: [why each is needed]
- Steering compliance: [principles maintained - SOLID, DRY, etc.]

### Technology Stack

| Layer | Choice / Version | Role in Feature | Notes |
|-------|------------------|-----------------|-------|
| Runtime | Python 3.10+ / FastAPI (async) | Core framework | Use `async/await` for all I/O |
| DI Container | `src/core/di/container.py` | Service registration | Singleton/Scoped/Transient lifetimes |
| Initialization | Staged (`src/core/app/stages/`) | Service bootstrap | Respect stage dependencies |
| Connectors | `src/connectors/base.LLMBackend` | Backend adapters | Implement `chat_completions`, `initialize` |
| Config | `src/core/config/app_config.py` | Configuration | YAML + ENV + CLI precedence |
| Wire Capture | CBOR (`var/wire_captures_cbor/`) | Traffic debugging | Optional, configurable |

> Keep rationale concise here and, when more depth is required (trade-offs, benchmarks), add a short summary plus pointer to the Supporting References section and `research.md` for raw investigation notes.

## System Flows

Provide only the diagrams needed to explain non-trivial flows. Use pure Mermaid syntax. Common patterns:
- Sequence (multi-party interactions)
- Process / state (branching logic or lifecycle)
- Data / event flow (pipelines, async messaging)

Skip this section entirely for simple CRUD changes.
> Describe flow-level decisions (e.g., gating conditions, retries) briefly after the diagram instead of restating each step.

## Requirements Traceability

Use this section for complex or compliance-sensitive features where requirements span multiple domains. Straightforward 1:1 mappings can rely on the Components summary table.

Map each requirement ID (e.g., `2.1`) to the design elements that realize it.

| Requirement | Summary | Components | Interfaces | Flows |
|-------------|---------|------------|------------|-------|
| 1.1 | | | | |
| 1.2 | | | | |

> Omit this section only when a single component satisfies a single requirement without cross-cutting concerns.

## Components and Interfaces

Provide a quick reference before diving into per-component details.

**DI Registration Strategy**: For each new service, specify:
- Lifetime: `Singleton` (one instance) / `Scoped` (per-request) / `Transient` (new each time)
- Interface binding: `IServiceName` -> `ServiceNameImpl`
- Factory vs direct registration

- Summaries can be a table or compact list. Example table:
  | Component | Layer | Intent | Req Coverage | DI Lifetime | Contracts |
  |-----------|-------|--------|--------------|-------------|-----------|
  | ExampleService | `src/core/services/` | Processes XYZ | 1, 2 | Singleton | IExampleService |
  | ExampleConnector | `src/connectors/` | Backend adapter | 3 | Singleton | LLMBackend |
- Only components introducing new boundaries (e.g., services, connectors, middleware) require full detail blocks.

Group detailed blocks by architectural layer. For each detailed component, list requirement IDs as `2.1, 2.3` (omit "Requirement").

### Services Layer (`src/core/services/`)

#### [ServiceName]

| Field | Detail |
|-------|--------|
| Intent | 1-line description of the responsibility |
| Requirements | 2.1, 2.3 |
| Interface | `I[ServiceName]` in `src/core/interfaces/` |
| DI Lifetime | Singleton / Scoped / Transient |

**Responsibilities & Constraints**
- Primary responsibility
- Single Responsibility Principle adherence
- Data ownership / invariants

**Dependencies (via DI)**
- Inbound: `IServiceProvider.get_required_service(DependencyType)`
- Outbound: Services this component calls
- External: HTTP clients, file system access

**Contracts**: Service [ ] / Event [ ] / Middleware [ ]  <-- check only the ones that apply.

##### Service Interface
```python
from abc import ABC, abstractmethod

class I[ServiceName](ABC):
    @abstractmethod
    async def method_name(self, input: InputType) -> OutputType:
        """Docstring with preconditions/postconditions."""
        ...
```
- Preconditions: Input validation requirements
- Postconditions: State changes / return guarantees
- Invariants: Must remain true before/after

##### DI Registration (in appropriate stage)
```python
def _factory(provider: IServiceProvider) -> ServiceName:
    dep = provider.get_required_service(IDependency)
    return ServiceName(dep)

services.add_singleton(IServiceName, implementation_factory=_factory)
```

### Connectors Layer (`src/connectors/`)

#### [ConnectorName]

| Field | Detail |
|-------|--------|
| Intent | Backend adapter for [provider] |
| Base Class | `LLMBackend` |
| Backend Type | `backend_type = "[provider_name]"` |

**Required Implementations**
- `async def initialize(self, **kwargs) -> None`
- `async def chat_completions(...) -> ResponseEnvelope | StreamingResponseEnvelope`
- `def get_available_models(self) -> list[str]` (with vendor prefix)

**Activity Tracking** (if enabled)
- Use `self.track_connection()` context manager
- Call `self.increment_rx()` / `self.increment_tx()` for byte counting

### Middleware / Handlers

#### [MiddlewareName]

| Field | Detail |
|-------|--------|
| Intent | Request/response transformation |
| Registration | Stage where registered |

**Implementation Notes**
- Integration: Where in pipeline
- Validation: Input checks
- Risks: Performance impact, error propagation

## Data Models

Focus on the portions of the data landscape that change with this feature.

- Cross-layer / cross-domain data passed between components should use standardized contracts (prefer **Pydantic v2 models** in `src/core/domain/`); avoid passing ad-hoc `dict[...]` payloads or wide unions between layers.

### Domain Model (`src/core/domain/`)
- Domain entities and value objects
- Business rules & invariants
- Pydantic models for validation

### DTOs and Envelopes (`src/core/domain/responses.py`)
- `ResponseEnvelope` for non-streaming
- `StreamingResponseEnvelope` for streaming
- Translation between API formats

### Configuration Model (`src/core/config/`)
- New config fields in `AppConfig`
- Schema updates in `config/schemas/`
- CLI flag additions in `src/core/cli.py`

Skip subsections that are not relevant to this feature.

## Error Handling

### Error Hierarchy
All errors extend `LLMProxyError` from `src/core/common/exceptions.py`.

| Error Type | HTTP Status | Use Case |
|------------|-------------|----------|
| `ValidationError` | 400 | Invalid input |
| `AuthenticationError` | 401 | Auth failures |
| `RoutingError` | 403 | Policy restrictions |
| `RateLimitExceededError` | 429 | Rate limiting |
| `BackendError` | 502 | Backend failures |
| `ServiceUnavailableError` | 503 | Temporary unavailability |

### Error Strategy
- Catch specific exceptions, never bare `except Exception`
- Log with `exc_info=True` for stack traces
- Use structured error responses via `to_dict()`

### Health-Aware Integration
If feature affects backend health:
- Implement `IHealthAware` interface
- Handle `on_endpoint_healthy` / `on_endpoint_unhealthy` callbacks
- Integrate with circuit breaker via `is_backend_functional()`

## Testing Strategy

> **TDD Approach**: Write test -> Fail -> Code -> Pass. Run related tests first, then full suite.

### Test Organization
Tests mirror source structure under `tests/`:
- `tests/unit/` - Isolated unit tests (mocked dependencies)
- `tests/integration/` - Cross-component tests
- `tests/property/` - Hypothesis property-based tests
- `tests/behavior/` - Behavior-driven tests

### Unit Tests (`tests/unit/`)
- [ ] Service logic with mocked DI dependencies
- [ ] Interface contract compliance
- [ ] Error handling paths
- [ ] Edge cases and boundary conditions

### Integration Tests (`tests/integration/`)
- [ ] DI container wiring verification
- [ ] End-to-end request flow
- [ ] Backend connector integration
- [ ] Middleware chain behavior

### Property Tests (`tests/property/`)
- [ ] Invariant preservation under random inputs
- [ ] State machine properties
- [ ] Serialization roundtrip

### Test Commands
```bash
# Fast (unit only)
./.venv/Scripts/python.exe -m pytest tests/unit/path/to/test.py -v

# Full suite
./.venv/Scripts/python.exe -m pytest -m "not slow"

# With coverage
./.venv/Scripts/python.exe -m pytest --cov=src --cov-report=term-missing
```

## Optional Sections (include when relevant)

### Security Considerations
_Use this section for features handling auth, sensitive data, external integrations, or user permissions._
- Never expose API keys in logs (use redaction middleware)
- Validate all external inputs
- Follow principle of least privilege for permissions

### Performance & Scalability
_Use this section when performance targets, high load, or scaling concerns exist._
- Async I/O for all network operations
- Connection pooling for HTTP clients
- Consider wire capture overhead (CBOR compression)

### Stage Registration
If feature requires initialization stage changes:
```
Infrastructure -> Core Services -> Backends -> Controllers
```
- Which stage registers this component?
- What are the stage dependencies?
- Validation requirements before proceeding?

## Supporting References (Optional)
- Create this section only when keeping the information in the main body would hurt readability.
- Link to the supporting references from the main text instead of inlining large snippets.
- Background research notes and comparisons continue to live in `research.md`, but their conclusions must be summarized in the main design.
