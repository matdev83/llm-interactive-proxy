# Command Handling Refactor Plan

## Objectives
- Eliminate duplicated command execution stacks and converge on a single, SOLID-compliant architecture.
- Guarantee interactive command detection only triggers on the tail of the latest user message (ignoring trailing whitespace) while remaining performant.
- Improve maintainability by clearly separating parsing, routing, validation, and state mutation concerns with dependency-injected services.
- Restore confidence in the command pipeline via comprehensive unit, integration, and regression test coverage.

## Current Pain Points
- Two parallel command stacks (`src/core/commands/handlers/*` vs. `src/core/domain/commands/*`) constantly drift, causing regressions (e.g., `SetCommandHandler` vs. `SetCommand`, `UnsetCommandHandler` vs. `UnsetCommand`).
- `NewCommandService` scans historical user messages and allows mid-message matches unless strict mode is explicitly enabled, violating the expected “last message & tail only” rule.
- Parser abstractions are inconsistent: the `ICommandParser` interface advertises an async, multi-command API while the concrete parser is synchronous, single-command.
- Environment policy checks (`STATIC_ROUTE`) live inside handlers instead of a dedicated policy service, making behaviour implicit and brittle.
- Legacy infrastructure (CommandRegistry, CommandDetector, CommandArgumentParser, SecureCommandFactory) remains registered but unused, creating confusion and extra maintenance.

## Target Architecture
1. **CommandDetectionPipeline**
   - `CommandTailExtractor`: isolates the final non-empty segment of the latest user message (string or structured parts).
   - `CommandParser` (synchronous): returns all trailing commands plus offsets; aligns with an updated `ICommandParser` protocol.
   - `CommandMatchFilter`: enforces end-of-message policy and resolves configured prefixes.
2. **CommandRouter**
   - Uses a single registry (DI-provided) of domain-level command implementations (`BaseCommand` subclasses).
   - Interactive adapters (`ICommandHandler` implementations) become thin delegators or are replaced with direct routing to domain commands.
3. **Policy & State Services**
   - `ICommandPolicyService`: surfaces feature toggles (strict detection default, command enablement, static routing constraints).
   - `ICommandStateService`: encapsulates session state mutations so commands never touch environment variables directly.
4. **CommandService v2**
   - Consumes the detection pipeline, router, and policy/state services.
   - Processes only the most recent user message and produces `ProcessedResult` with precise modifications.
5. **DI Cleanup**
   - Register only the new pipeline components and prune obsolete singletons (legacy registry/detector/argument parser).

## Refactor Phases & Tasks

### Phase 1: Detection Pipeline Overhaul
- [x] Introduce `CommandTailExtractor` with unit tests for strings and multipart content.
- [x] Redesign `CommandParser` & `ICommandParser` to support synchronous multi-command extraction (update interface, docs, tests).
- [x] Implement `CommandMatchFilter` to enforce prefix + end-of-message matching, including whitespace tolerance.
- [x] Update `NewCommandService` (or replacement) to use the pipeline and restrict processing to the last user message.

### Phase 2: Command Routing Consolidation
- [x] Decide on canonical command implementation layer (domain commands) and document adapter strategy.
- [x] Replace `SetCommandHandler`, `UnsetCommandHandler`, and similar legacy handlers with thin adapters to domain commands.
- [x] Remove duplicated logic from handlers; port missing behaviour from handlers into domain commands where needed.
- [x] Ensure failover commands use shared router/registry while still supporting secure state access.

### Phase 3: Policy & State Abstraction
- [x] Create `ICommandPolicyService` pulling configuration from `AppConfig`, CLI overrides, and session/app state.
- [x] Move static routing and interactive-command disable checks into the policy service; update commands to query policies instead of environment variables.
- [x] Introduce `ICommandStateService` (wrapper around `SessionService`/state mutation helpers) to centralize updates.

### Phase 4: Dependency Injection & Cleanup
- [x] Update `src/core/di/services.py` and `CommandStage` to wire new services and drop unused registrations (CommandRegistry, CommandDetector, etc.).
- [ ] Remove unused legacy modules or mark them deprecated with clear documentation.
- [ ] Adjust configuration schema & CLI flags to align with new defaults (strict detection enabled by default, optional overrides).

### Phase 5: Testing & Regression Safety
- [x] Expand unit tests for parser, extractor, policy logic, and router.
- [x] Refresh integration tests covering command execution scenarios (set/unset/model/failover/loop detection).
- [x] Add regression tests for multi-command lines, trailing whitespace, multipart content, and command-only requests.
- [ ] Validate no regression in redaction middleware or downstream processors (update mocks as needed).

### Phase 6: Migration & Rollout
- [ ] Provide migration notes in `CHANGELOG.md` and `docs/` highlighting detection behaviour changes.
- [ ] Coordinate removal or archival of legacy fixtures relying on old behaviour.
- [ ] Introduce feature flags (if needed) for gradual rollout, defaulting to the new pipeline.

## Risk Mitigation
- Stage refactor by feature branch with feature flags to flip back if required.
- Keep legacy handlers available temporarily behind adapters until new pipeline is fully validated.
- Ensure redaction middleware and tooling reuse the shared detection pipeline to avoid divergence.

## Implementation Notes
- Default strict detection must be enforced in new policy service; CLI/config should only relax it explicitly.
- Domain commands that require secure state must receive dependencies through DI (SecureCommandFactory or successor) to preserve safety.
- After consolidation, delete or archive unused handler tests; replace them with domain command coverage to reduce duplication.
- Set/unset interactive handlers now wrap the domain command implementations via `SessionStateAdapter`, establishing domain commands as the canonical execution layer while preserving legacy messaging semantics.
- CommandStage registers the shared policy/state helpers and relies on the new pipeline wiring instead of the legacy `CommandRegistry` auto-population path.
- Remaining legacy fixtures to revisit: `tests/unit/fixtures/command_fixtures.py` still exports `NewCommandService` for compatibility; evaluate removal once downstream consumers migrate to direct DI resolution.
- Feature flag assessment: current rollout keeps the new pipeline as the default; introduce a gating flag only if downstream regressions surface during staging.
