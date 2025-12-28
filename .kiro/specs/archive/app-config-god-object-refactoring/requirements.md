# Requirements Document

## Introduction

This document specifies the requirements for refactoring `src/core/config/app_config.py`, a ~2895 LOC “God Object” configuration module that currently mixes: configuration domain models, YAML loading and schema/semantic validation, environment parsing, parameter source tracking, backend instance discovery, dynamic backend behavior, and miscellaneous helpers.

The refactoring must produce a modular, layered configuration subsystem aligned with the project’s staged initialization and DI architecture. The outcome must be testable in isolation and must not introduce a new “God object/module” elsewhere.

Unless explicitly stated as a breaking change in these requirements, external behavior and public entry points must remain compatible (including config precedence rules).

## Glossary

- **Config_Subsystem**: The runtime configuration pipeline responsible for producing an `AppConfig` instance from defaults, config files, environment variables, and CLI overrides.
- **AppConfig**: The top-level configuration object used across the proxy (`src/core/config/app_config.py`).
- **Config_Domain_Models**: Pydantic/DomainModel-based configuration models (e.g., auth, logging, session, backends).
- **Config_Source**: An origin of configuration values (defaults, YAML file, environment variables, CLI).
- **Config_Precedence**: The rule ordering for conflicts among sources (CLI > ENV > YAML > defaults).
- **ParameterResolution**: A tracking mechanism for recording the resolved value and its source (`src/core/config/parameter_resolution.py`).
- **Backend_Settings**: The configuration section representing backend definitions and instances (default backend, routing, per-backend overrides).
- **Backend_Instance**: A named backend connector instance (e.g., `openai.1`) discovered via env vars and/or per-instance YAML files.
- **Schema_Validation**: YAML schema validation against `config/schemas/app_config.schema.yaml`.
- **Semantic_Validation**: Cross-field and domain-specific validation currently applied via `src/core/config/semantic_validation.py`.
- **DI Container**: The ServiceCollection-based DI system used to provide services and configuration (`src/core/di/container.py` and registrations in startup stages).

## Requirements

### Requirement 1: Preserve Public Configuration Contract

**User Story:** As a maintainer, I want the configuration entry points to remain compatible, so that existing code and integrations continue to work while internal structure improves.

#### Acceptance Criteria

1.1 WHEN `load_config(config_path=..., environ=..., resolution=...)` is invoked THEN the Config_Subsystem SHALL return an `AppConfig` that is semantically equivalent to the current implementation for the same inputs
1.2 WHEN `AppConfig.from_env(environ=..., resolution=...)` is invoked THEN the Config_Subsystem SHALL apply the same environment variable interpretation as the current implementation
1.3 WHEN the config file is missing THEN the Config_Subsystem SHALL continue startup using defaults + environment (and SHOULD emit an equivalent warning)
1.4 WHEN an unsupported config file format is provided THEN the Config_Subsystem SHALL fail with a clear, testable error
1.5 WHEN `AppConfig.model_dump()` (or equivalent serialization) is used THEN dynamic backend instance data SHALL remain representable in the serialized output

### Requirement 2: Enforce Layered Separation of Concerns

**User Story:** As a developer, I want configuration domain models separated from parsing and I/O, so that each concern can be reasoned about and tested independently.

#### Acceptance Criteria

2.1 THE Config_Subsystem SHALL separate Config_Domain_Models from source adapters (YAML, environment) such that domain models contain no filesystem or environment reads
2.2 WHEN a configuration source is read THEN the source adapter SHALL be the only layer permitted to touch `os.environ`, filesystem paths, or current working directory
2.3 WHEN configuration values are merged THEN the merge behavior SHALL be implemented in a dedicated component that is independent of YAML parsing and environment parsing
2.4 WHEN validations are executed THEN schema validation and semantic validation SHALL be invoked via dedicated validation components with explicit inputs/outputs
2.5 WHEN new configuration domains are added THEN the developer SHALL be able to extend the domain model and register a new parser/validator without modifying unrelated domains

### Requirement 3: Maintain Config Precedence and Source Tracking

**User Story:** As an operator, I want consistent precedence and explainability, so that I can understand where each configuration value came from.

#### Acceptance Criteria

3.1 WHEN multiple Config_Sources provide the same setting THEN the Config_Subsystem SHALL resolve it using Config_Precedence (CLI > ENV > YAML > defaults)
3.2 WHEN a configuration value is resolved from any source THEN the Config_Subsystem SHALL record the effective value and its source in ParameterResolution
3.3 WHEN a configuration file provides values THEN the Config_Subsystem SHALL record the file origin path in ParameterResolution for those values
3.4 WHEN environment variables provide values THEN the Config_Subsystem SHALL record the environment variable name as origin in ParameterResolution
3.5 WHEN the system is configured without an explicit ParameterResolution object THEN the Config_Subsystem SHALL still operate correctly and MAY create an internal tracker

### Requirement 4: YAML Schema and Semantic Validation Behavior

**User Story:** As a maintainer, I want validation to remain correct and testable, so that invalid configurations fail early with actionable feedback.

#### Acceptance Criteria

4.1 WHEN a YAML config file is provided THEN the Config_Subsystem SHALL validate it against the YAML schema (`config/schemas/app_config.schema.yaml`) before applying it
4.2 IF YAML schema validation fails THEN the Config_Subsystem SHALL fail with a clear, testable error that identifies the invalid portion
4.3 WHEN a YAML config file is provided THEN the Config_Subsystem SHALL execute semantic validation before returning `AppConfig`
4.4 IF semantic validation fails THEN the Config_Subsystem SHALL fail with a clear, testable error describing the semantic issue
4.5 WHEN tests provide a minimal configuration dict THEN validators SHALL support running in isolation without requiring a full application bootstrap

### Requirement 5: Backend Configuration and Instance Discovery Compatibility

**User Story:** As an operator, I want backend definitions and per-instance overrides to continue to work, so that backend configuration remains flexible across deployments.

#### Acceptance Criteria

5.1 WHEN registered backend connector types exist THEN the Config_Subsystem SHALL continue to support per-backend configuration sections (e.g., `backends.<backend_type>`)
5.2 WHEN backend instances are present via environment variables THEN the Config_Subsystem SHALL discover them and expose them as Backend_Instances in the effective configuration
5.3 WHEN backend instance YAML files exist under the backend instances directory THEN the Config_Subsystem SHALL load and merge them into the effective configuration with deterministic precedence
5.4 WHEN both an environment variable and an instance YAML file provide values for the same Backend_Instance THEN the Config_Subsystem SHALL apply a deterministic merge rule equivalent to the current behavior
5.5 WHEN an instance file references an unregistered connector THEN the Config_Subsystem SHOULD emit a warning and SHALL ignore that instance rather than crashing

### Requirement 6: Typed and Testable Backend Lookup API

**User Story:** As a developer, I want a stable backend lookup API, so that code can access backend configs without relying on fragile dynamic attribute mutation.

#### Acceptance Criteria

6.1 WHEN application code requests a backend configuration by backend type or instance name THEN the Config_Subsystem SHALL provide a consistent lookup method that returns `BackendConfig | None`
6.2 WHEN application code uses legacy attribute-style access to backend configs THEN the Config_Subsystem SHALL preserve equivalent behavior or provide a backward-compatible adapter
6.3 WHEN a backend config is missing THEN the lookup method SHALL return a safe default or `None` consistently (and MUST NOT silently create persistent hidden state without being explicit)
6.4 WHEN backend settings are serialized THEN the serialized form SHALL include both static backend sections and discovered backend instances
6.5 WHEN backend config lookup is tested THEN it SHALL be testable without importing backend connectors or requiring global registries to be mutated

### Requirement 7: DI Integration and Staged Initialization Alignment

**User Story:** As a platform developer, I want configuration assembly aligned with DI and staged startup, so that config loading is consistent across runtime and tests.

#### Acceptance Criteria

7.1 WHEN the application bootstraps via staged initialization THEN the effective `AppConfig` SHALL be registered as a singleton instance in the DI container
7.2 WHEN services require configuration THEN they SHALL receive `AppConfig` (or narrowed config sections) via DI rather than importing globals
7.3 WHEN tests build apps via test builders THEN the Config_Subsystem SHALL support injecting a prebuilt `AppConfig` instance without requiring filesystem/environment reads
7.4 WHEN configuration assembly needs dependencies (filesystem, env, validators, backend registry access) THEN those dependencies SHALL be injectable via DI

### Requirement 8: Error Handling and Logging Contracts

**User Story:** As an operator, I want configuration failures to be clearly reported, so that I can remediate misconfiguration quickly.

#### Acceptance Criteria

8.1 IF configuration loading fails THEN the Config_Subsystem SHALL raise a structured, testable exception type (not a bare `Exception`)
8.2 WHEN configuration loading fails due to parsing or validation THEN the error SHALL include enough context to locate the cause (file path, key path, or env var name when available)
8.3 WHEN configuration loading encounters recoverable conditions (e.g., missing optional instance dir) THEN the Config_Subsystem SHOULD log warnings and continue with safe defaults
8.4 WHEN configuration loading logs THEN it SHOULD use structured logging patterns consistent with the project (and MUST NOT log secrets such as API keys)

### Requirement 9: Testability and Deterministic Behavior

**User Story:** As a maintainer, I want the config pipeline to be testable with deterministic results, so that regressions are caught early and flakes are minimized.

#### Acceptance Criteria

9.1 WHEN unit tests run THEN each major configuration component (env parsing, YAML loading, merging, validation, backend discovery) SHALL be testable in isolation with injected fakes/mocks
9.2 WHEN integration tests run THEN the DI wiring for configuration assembly SHALL be verifiable without launching servers
9.3 WHEN configuration is built from the same inputs THEN the Config_Subsystem SHALL produce identical outputs deterministically
9.4 WHEN tests provide an explicit environment mapping THEN the Config_Subsystem MUST NOT read from process-global `os.environ`
9.5 WHEN tests provide a fake filesystem or temp directory THEN the Config_Subsystem MUST NOT rely on `Path.cwd()` implicitly

### Requirement 10: Maintainability Guardrails (No New God Objects)

**User Story:** As a maintainer, I want strict maintainability limits, so that configuration code remains readable and evolvable over time.

#### Acceptance Criteria

10.1 WHEN the refactor is complete THEN no touched production file in the Config_Subsystem SHALL exceed 600 lines of code
10.2 WHEN the refactor is complete THEN no touched production file in the Config_Subsystem SHALL exceed cyclomatic complexity (CC) 40
10.3 WHEN responsibilities are extracted THEN the refactor SHALL NOT consolidate them into a new single “god” module or “god” class; responsibilities SHALL be separated across cohesive components with explicit boundaries
10.4 WHEN new components are introduced THEN each SHALL have a single clearly stated responsibility and SHALL depend on abstractions rather than concrete low-level details where appropriate
10.5 WHEN configuration responsibilities move across layers THEN dependency direction SHALL follow the layered architecture (domain models independent of parsing and I/O)

