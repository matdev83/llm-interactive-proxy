# Architecture refactor tasks

Use this file to track the refactor steps. Check items as you complete them.

- [ ] **Create `IBackendConfigProvider` interface** — provide canonical BackendConfig access
- [ ] **Implement `BackendConfigProvider` adapter** for `AppConfig.backends` (handles dict or BackendSettings)
- [ ] **Register `BackendConfigProvider` in DI** inside `ApplicationBuilder._initialize_services`
- [ ] **Refactor `BackendService` constructor** to accept `IBackendConfigProvider` and remove dict/object branching
- [ ] **Move backend init logic into `BackendFactory.ensure_backend()`** and provide typed `BackendInitSpec`
- [ ] **Introduce `FailoverCoordinator`** to encapsulate complex vs simple failover strategies
- [ ] **Ensure single `httpx.AsyncClient` registered in DI and used everywhere**
- [ ] **Normalize config shapes early (in ApplicationBuilder)** so services assume canonical types
- [ ] **Extract and unit-test `BackendConfigProvider` behavior**
- [ ] **Update unit tests that relied on previous implicit shapes** (e.g., tests creating `_backends` directly)
- [ ] **Add integration tests for startup and backend probing under test env**
- [ ] **Run full test suite and fix regressions**

Notes:
- Start with the first three items — they are low-risk and unblock other refactors.
- After registering provider in DI, refactor `BackendService._get_or_create_backend` to use it (this is implemented in the codebase already).


