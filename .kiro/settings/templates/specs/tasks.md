# Implementation Plan

## Task Format Template

Use whichever pattern fits the work breakdown:

### Major task only
- [ ] {{NUMBER}}. {{TASK_DESCRIPTION}}{{PARALLEL_MARK}}
  - {{DETAIL_ITEM_1}} *(Include details only when needed. If the task stands alone, omit bullet items.)*
  - _Requirements: {{REQUIREMENT_IDS}}_

### Major + Sub-task structure
- [ ] {{MAJOR_NUMBER}}. {{MAJOR_TASK_SUMMARY}}
- [ ] {{MAJOR_NUMBER}}.{{SUB_NUMBER}} {{SUB_TASK_DESCRIPTION}}{{SUB_PARALLEL_MARK}}
  - {{DETAIL_ITEM_1}}
  - {{DETAIL_ITEM_2}}
  - _Requirements: {{REQUIREMENT_IDS}}_ *(IDs only; do not add descriptions or parentheses.)*

> **Parallel marker**: Append ` (P)` only to tasks that can be executed in parallel. Omit the marker when running in `--sequential` mode.
>
> **Optional test coverage**: When a sub-task is deferrable test work tied to acceptance criteria, mark the checkbox as `- [ ]*` and explain the referenced requirements in the detail bullets.

---

## Project-Specific Task Categories

### Interface Definition Tasks
- [ ] Define interface in `src/core/interfaces/` following `I[ServiceName]` naming
  - Include ABC with `@abstractmethod` decorators
  - Document preconditions/postconditions in docstrings
  - _Requirements: [IDs]_

### Service Implementation Tasks
- [ ] Implement service in `src/core/services/`
  - Extend appropriate base class or implement interface
  - Inject dependencies via constructor (DI-friendly)
  - Use `async/await` for I/O operations
  - _Requirements: [IDs]_

### DI Registration Tasks
- [ ] Register service in appropriate initialization stage
  - Choose correct lifetime: Singleton/Scoped/Transient
  - Create factory if dependencies require `IServiceProvider`
  - Add interface binding: `services.add_singleton(IService, ServiceImpl)`
  - _Requirements: [IDs]_

### Connector Implementation Tasks
- [ ] Implement connector in `src/connectors/`
  - Extend `LLMBackend` base class
  - Set `backend_type` class attribute
  - Implement `initialize()`, `chat_completions()`, `get_available_models()`
  - Include activity tracking if enabled
  - _Requirements: [IDs]_

### Configuration Tasks
- [ ] Add configuration support
  - Update `src/core/config/app_config.py` with new fields
  - Update schema in `config/schemas/app_config.schema.yaml`
  - Add CLI flags in `src/core/cli.py` if needed
  - Update `config/config.example.yaml`
  - _Requirements: [IDs]_

### Error Handling Tasks
- [ ] Define custom exceptions
  - Extend `LLMProxyError` from `src/core/common/exceptions.py`
  - Set appropriate `status_code`
  - Implement `to_dict()` for structured responses
  - _Requirements: [IDs]_

### Testing Tasks (TDD)
- [ ] Write unit tests FIRST (Red phase)
  - Create test file in `tests/unit/` mirroring source structure
  - Mock DI dependencies
  - Cover happy path, error cases, edge conditions
  - _Requirements: [IDs]_

- [ ] Write integration tests
  - Create test file in `tests/integration/`
  - Test DI wiring and component interaction
  - Use fixtures from `tests/conftest.py`
  - _Requirements: [IDs]_

- [ ] Write property tests (if applicable)
  - Create test file in `tests/property/`
  - Use Hypothesis for invariant testing
  - _Requirements: [IDs]_

### Verification Tasks
- [ ] Run test suite and fix failures
  ```bash
  ./.venv/Scripts/python.exe -m pytest tests/unit/[path] -v
  ./.venv/Scripts/python.exe -m pytest -m "not slow"
  ```
  - _Requirements: [IDs]_

- [ ] Run linting and type checks
  ```bash
  ./.venv/Scripts/python.exe -m ruff check . --fix
  ./.venv/Scripts/python.exe -m mypy src/
  ```
  - _Requirements: [IDs]_

---

## CRITICAL: Post-Edit QA Workflow for Python Files

**MANDATORY**: After editing ANY Python (*.py) file, agents MUST immediately run the following QA command before proceeding to the next file or committing:

```powershell
./.venv/Scripts/python.exe -m ruff check --fix <modified_filename> && ./.venv/Scripts/python.exe -m black <modified_filename> && ./.venv/Scripts/python.exe -m mypy <modified_filename>
```

**Rules**:
1. Replace `<modified_filename>` with the exact path to the changed file
2. Run this command AFTER each Python file edit (not in batches)
3. Fix any reported errors before proceeding
4. This applies to ALL Python files: source, tests, scripts, configs

**Example**:
```powershell
# After editing src/core/services/my_service.py
./.venv/Scripts/python.exe -m ruff check --fix src/core/services/my_service.py && ./.venv/Scripts/python.exe -m black src/core/services/my_service.py && ./.venv/Scripts/python.exe -m mypy src/core/services/my_service.py
```

**Why This Matters**:
- Catches errors immediately while context is fresh
- Prevents cascading failures across multiple files
- Ensures code quality before integration tests
- Maintains project standards throughout implementation

---

## Task Ordering Guidelines

1. **Interfaces before implementations** - Define contracts first
2. **Services before connectors** - Core logic before adapters
3. **Tests alongside code** - TDD: test -> implement -> verify
4. **DI registration after implementation** - Wire up after code exists
5. **Integration tests last** - Verify full flow after components work

## Checklist Before Marking Complete

- [ ] All acceptance criteria from requirements are covered
- [ ] Unit tests pass with good coverage
- [ ] Integration tests verify DI wiring
- [ ] No lint errors (`ruff check .`)
- [ ] Type checks pass (`mypy src/`)
- [ ] Error handling uses `LLMProxyError` hierarchy
- [ ] Async/await used correctly (no blocking I/O)
- [ ] Configuration documented if added
