# Implementation Orchestration Contract

This file defines the lead/specialist split used for `unification-of-request-processing` execution waves.

## Agent Roles

- **Lead orchestrator**
  - Owns wave admission/exit criteria.
  - Decides sequencing and rollback actions.
  - Approves `tasks.md` checkbox updates after evidence is complete.
- **Traceability specialist**
  - Maps each task to requirement IDs and design invariants.
  - Flags out-of-scope edits before coding starts.
- **RED specialist**
  - Adds failing tests first for each wave/task.
  - Confirms failures represent missing behavior rather than test defects.
- **GREEN specialist**
  - Implements minimum code required to pass the new tests.
  - Keeps migration gates default-off unless a task explicitly requires stage enablement.
- **Refactor specialist**
  - Improves structure after green without changing behavior.
- **Verification specialist**
  - Runs per-file QA (`ruff`, `black`, `mypy`), targeted tests, then broader suites.
  - Provides pass/fail evidence for wave closure.

## Handoff Checklist (Per Task)

1. Traceability map recorded (requirements + invariants).
2. RED test added and failing.
3. GREEN implementation merged.
4. Refactor completed (if needed).
5. QA commands and tests are green.
6. Lead updates `tasks.md` checkbox.

## Failure Handling Contract

- Freeze next-wave work on broad regression.
- Keep migration gates default-off.
- Reproduce with minimal targeted tests.
- Resume only after the current wave gate turns green again.
