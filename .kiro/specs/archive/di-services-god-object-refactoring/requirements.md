# Requirements Document

## Project Description (Input)
Effort: Refactor src/core/di/services.py God-Object to make it smaller and less complicated. Problem statement below: ``` Codebase analysis revealed that this file: src/core/di/services.py has many signs of being a God-Object anti-pattern. File is very large and comples, has too many responsibilities. We need to refactor it to follow design goals of this project, which are: layered, modular architecture with loose coupling and strong separation of concerns, following of all SOLID principles, proper use of DI for inversion and instance management, following of DRY principle, use of the well established OOP design patterns. After this refactor and splitting it into multiple smaller files/components, none of the files should exceed 600 LOC and have complexity of over 50 (CC). Code should be easy to maintain, debug and test. ```

## Introduction
This specification refactors the DI registration layer currently centralized in `src/core/di/services.py` to eliminate the God-Object anti-pattern while preserving existing proxy behavior and staged initialization.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining DI/service wiring and adding new features/backends
- Operators deploying and debugging the proxy in different environments

## Requirements

### Requirement 1: Behavioral Compatibility and Startup Integrity
**Objective:** As an operator, I want the DI refactor to preserve application behavior and startup stability, so that deployments are not disrupted.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1. When the proxy application starts, the proxy application shall complete staged initialization successfully without DI registration errors.
1.2. When an existing component resolves a previously-registered dependency, the DI container shall resolve the same effective implementation type and lifetime semantics as before the refactor.
1.3. If a required dependency cannot be resolved at runtime, then the DI container shall raise a deterministic, actionable error that identifies the missing service type and the resolution path.
1.4. When the existing automated test suites are executed, the system shall pass without regressions attributable to DI wiring changes.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 2: Modular DI Registration (God-Object Elimination)
**Objective:** As a developer, I want DI registrations split into cohesive modules with clear responsibility boundaries, so that changes are easier to understand, debug, and test.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1. The DI registration layer shall be decomposed into multiple cohesive modules such that `src/core/di/services.py` is no longer the single place where most registrations and wiring logic reside.
2.2. When a developer needs to locate registrations for a specific feature area (for example routing, captures, steering/safety, request processing, backends, or persistence), the DI registration layer shall provide a dedicated, discoverable entry point for that feature area.
2.3. When registration modules are imported, the DI registration layer shall not perform network I/O, open database connections, or mutate global runtime state beyond defining registrations.
2.4. The DI registration layer shall not introduce new circular imports among DI modules and the service/adapter layers.

#### Technical Constraints
- DI integration: Services registered via `ServiceCollection`
- Staged init alignment: DI wiring remains compatible with `src/core/app/stages/` ordering

### Requirement 3: Separation of Concerns and Layering
**Objective:** As a developer, I want DI wiring to respect the project’s layered architecture and SOLID principles, so that modules remain loosely coupled and test seams stay intact.

**Priority:** P1 (High)

#### Acceptance Criteria
3.1. The DI registration layer shall only define dependency registrations and composition wiring, and shall not implement business logic, request processing logic, or protocol-specific behavior.
3.2. Where a service contract exists as an interface in `src/core/interfaces/`, the DI registration layer shall register that interface to a concrete implementation so that consumers can depend on the interface.
3.3. When optional features are disabled by configuration, the DI registration layer shall not require those feature implementations to be instantiated or imported in order for core proxy startup to succeed.

#### Technical Constraints
- Interfaces: Contracts live under `src/core/interfaces/` and follow `I*` naming
- Error model: Failures surface through the project’s error handling conventions

### Requirement 4: Code Size and Complexity Limits
**Objective:** As a maintainer, I want objective size and complexity limits applied to DI wiring modules, so that the refactor results in sustained maintainability improvements.

**Priority:** P0 (Critical)

#### Acceptance Criteria
4.1. The DI registration code introduced or modified for this refactor shall be structured so that no single DI registration module exceeds 600 total lines of code.
4.2. When the project is linted with Ruff using `C901` complexity checks configured with a maximum complexity of 50, the DI registration modules shall not produce cyclomatic complexity violations.
4.3. The DI registration layer shall minimize duplication in registration logic so that a given service registration pattern is defined once and reused consistently.

#### Technical Constraints
- Tooling: The repository uses Ruff and Black for quality gates
- Type checking: Mypy is enabled for `src/` and untyped defs are disallowed

## Non-Functional Requirements

### NFR 1: Performance
- The DI registration refactor shall not introduce additional per-request dependency construction beyond what is required by existing service lifetimes.
- When the proxy application starts, the DI registration layer shall avoid expensive computations at import time to keep startup responsive.

### NFR 2: Reliability
- When failures occur during staged initialization, the system shall fail fast with error messages sufficient to diagnose missing registrations or invalid configuration.
- The DI registration refactor shall preserve the existing staged initialization ordering and service availability guarantees.

### NFR 3: Observability
- The DI registration refactor shall preserve existing logging, usage tracking, and wire capture wiring so that operators retain equivalent observability.
- When diagnostic features (for example wire capture) are enabled, the system shall continue to emit captures to the configured locations.

### NFR 4: Security
- The DI registration refactor shall preserve existing safety features wiring (for example file access sandboxing and tool access control) so that protections are not weakened.
- The DI registration refactor shall not introduce new logging of sensitive secrets (for example API keys) beyond current behavior.

## Glossary
| Term | Definition |
|------|------------|
| DI registration layer | The set of modules responsible for registering services into the `ServiceCollection`/`IServiceProvider` container |
| God-Object | A single module/class that accumulates unrelated responsibilities and becomes difficult to maintain |
| Staged init | The project’s ordered startup phases under `src/core/app/stages/` |
| Service lifetime semantics | Rules governing how the DI container instantiates and reuses service instances |
