# Testing & TDD (Steering)

## Testing Philosophy

This project uses **Test-Driven Development (TDD)** as the default workflow:

- **Red → Green → Refactor**: start with a failing test that describes the desired behavior, implement the minimal code to pass, then refactor safely.
- **Tests are the primary specification**: tests should describe the system’s externally observable behavior (contracts), not internal implementation details.
- **Regression protection**: tests exist to prevent reintroducing previously fixed bugs and to lock in API/behavioral contracts across refactors.

## “Tests as Executable Specification” Bar

Created tests must be **sufficiently detailed** that a maintainer could re-create the intended implementation from the tests alone if source code was accidentally lost.

Practically, this means tests should:

- **Define the contract**: cover inputs/outputs, edge cases, and error handling (including status codes and error payloads where applicable).
- **Encode invariants**: assert what must always be true, not just “happy path” output.
- **Specify side effects**: verify important effects such as persistence, capture behavior, usage accounting, routing choices, and emitted events where relevant.
- **Cover boundary conditions**: validate behavior at interfaces between services/adapters (DI seams), not only in isolated units.
- **Stay deterministic**: avoid flaky timing/network dependencies; use fakes/fixtures where needed to make behavior reproducible.

Non-goals for tests:

- Duplicating implementation line-by-line.
- Overfitting to internal call graphs or private helper functions.

## What “Good Coverage” Looks Like Here

- **Unit tests**: pin domain/service behavior with clear inputs/outputs and targeted error cases.
- **Integration/behavior tests**: validate realistic request flows across key components, including streaming where applicable.
- **Property tests** (when useful): validate invariants over a range of generated inputs (e.g., parsing/transform pipelines).

---

_Updated: 2025-12-27_
_Reason: Clarify that TDD is the default workflow and raise the bar for tests as executable specifications_
