# Tasks

## Task 1: Wire Unified Steering Handler (Completed)
- Map to requirements: 1, 3
- Steps:
  1. Add UnifiedSteeringHandler implementing IToolCallHandler that extracts/normalizes commands once and iterates configured policy list with priority short-circuit. (Done)
  2. Emit single structured telemetry/log entry per tool call capturing evaluated policies and outcome. (Done)
  3. Add config surface to set/override policy order and feature flag to toggle unified vs legacy handlers. (Done)

## Task 2: Implement ISteeringPolicy Contract and Shared Models (Completed)
- Map to requirements: 1, 3, 4
- Steps:
  1. Define ISteeringPolicy interface and SteeringResult model. (Done)
  2. Provide command parsing/normalization helper for policies to reuse. (Done)
  3. Document usage pattern for adding new policies (inline example or docstring). (Done)

## Task 3: Build SessionStateStore (TTL/LRU) (Completed)
- Map to requirements: 2, 4
- Steps:
  1. Implement async-safe TTL + LRU eviction with per-session buckets and configurable TTL/max entries. (Done)
  2. Provide lazy eviction on access and an optional prune hook. (Done)
  3. Default config aligns with legacy reminder/pytest handlers’ behavior. (Done)

## Task 4: Migrate Existing Policies (Completed)
- Map to requirements: 1, 2, 3
- Steps:
  1. InlinePython → InlinePythonPolicy using shared command parsing. (Done)
  2. PytestFullSuite → PytestFullSuitePolicy using SessionStateStore for TTL/reminder logic. (Done)
  3. ConfigSteering → ConfiguredRulesPolicy using shared parsing; ensure priority preserved. (Done)
  4. Keep legacy wiring behind feature flag for fallback. (Done)

## Task 5: Testing and Parity Verification (Completed)
- Map to requirements: 3, 4
- Steps:
  1. Unit tests for policy ordering, no-match path, and error containment. (Done)
  2. SessionStateStore tests for TTL/LRU eviction and concurrent access. (Done)
  3. Migration parity tests asserting legacy behaviors for InlinePython, Pytest full-suite, and Configured rules. (Done)
  4. Document/execute targeted pytest command for this suite. (Done)

## Task 6: Externalize Hardcoded Steering Prompts (Completed)
- Map to requirements: 1, 4
- Steps:
  1. Identify all hardcoded steering prompt strings in policies (InlinePython, PytestFullSuite, ApplyDiff rule). (Done)
  2. Implement override mechanism to load prompts from Markdown files in `config/prompts/` if present. (Done)
  3. Ensure fallback to original hardcoded strings if override files are missing to preserve parity. (Done)
  4. Update policy constructors and DI registration to support optional prompt paths. (Done)
