# Testing Patterns

**Analysis Date:** 2026-04-04

## Test Framework

**Runner:**
- Pytest (`pytest==8.3.2` in `pyproject.toml`)
- Config: `pyproject.toml` (`[tool.pytest.ini_options]`)
- Async support: `pytest-asyncio==0.23.7` with `--asyncio-mode=auto` (`pyproject.toml`)
- Parallelization: `pytest-xdist==3.6.1` with `-n 4 --dist=loadfile` in default addopts (`pyproject.toml`)

**Assertion Library:**
- Native `assert` statements with `pytest` helpers (`pytest.raises`, markers, fixtures), for example in `tests/unit/core/config/test_auto_append_first_prompt.py` and `tests/unit/core/services/test_request_transform_pipeline.py`.

**Run Commands:**
```bash
./.venv/Scripts/python.exe -m pytest                         # Run all tests
./.venv/Scripts/python.exe -m pytest --testmon               # Incremental rerun (testmon)
./.venv/Scripts/python.exe -m pytest --cov=src --cov-report=term-missing --cov-report=xml  # Coverage report
```

## Test File Organization

**Location:**
- Primary test root is `tests/` (`testpaths = ["tests"]` in `pyproject.toml`).
- Tests are organized by type and scope: `tests/unit/`, `tests/integration/`, `tests/property/`, `tests/regression/`, `tests/behavior/`, `tests/streaming_regression/`.

**Naming:**
- Use `test_*.py` naming for test files (for example `tests/unit/connectors/test_openai_codex.py`).
- Use `conftest.py` at multiple levels for scoped fixtures/hooks (for example `tests/conftest.py`, `tests/unit/conftest.py`, `tests/integration/conftest.py`, `tests/property/conftest.py`).

**Structure:**
```text
tests/
  conftest.py
  unit/
  integration/
  property/
  regression/
  behavior/
  streaming_regression/
```

## Test Structure

**Suite Organization:**
```python
@pytest.fixture
def basic_request() -> ChatRequest:
    return ChatRequest(model="gpt-4", messages=[ChatMessage(role="user", content="Hello")])


@pytest.mark.asyncio
async def test_transform_pipeline_preserves_ordering(...):
    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    ...
    assert transformation_order == ["redaction", "auto_append_first_user", "edit_precision", "tool_filtering", "quality_verifier_steering"]
```
- Pattern source: `tests/unit/core/services/test_request_transform_pipeline.py`.

**Patterns:**
- Setup pattern: prefer fixtures for reusable setup and dependency wiring (`tests/conftest.py`, `tests/unit/core/services/test_request_transform_pipeline.py`).
- Teardown pattern: use `yield` fixtures and explicit cleanup in `finally` blocks when resources are opened (`tests/conftest.py`, `tests/integration/test_gemini_end_to_end.py`).
- Assertion pattern: assert shape + semantic values, not just truthiness (for example request payload assertions in `tests/unit/openrouter_connector_tests/test_non_streaming_success.py`).

## Mocking

**Framework:** `unittest.mock` + `pytest-httpx` + `respx`

**Patterns:**
```python
httpx_mock.add_response(url=f"{TEST_OPENROUTER_API_BASE_URL}/chat/completions", method="POST", json=mock_response_payload, status_code=200)
response_envelope = await openrouter_backend.chat_completions(...)
requests = httpx_mock.get_requests()
assert requests
```
- Pattern source: `tests/unit/openrouter_connector_tests/test_non_streaming_success.py`.

```python
with patch.object(openai_codex_backend, "_validate_runtime_credentials", return_value=(True, [])):
    await openai_codex_backend.chat_completions(...)
```
- Pattern source: `tests/unit/connectors/test_openai_codex.py`.

**What to Mock:**
- Outbound HTTP boundaries via `httpx_mock` or `respx` (for example `tests/unit/openrouter_connector_tests/test_non_streaming_success.py`, `tests/integration/test_nvidia_backend_http_e2e.py`).
- Internal side effects and optional integrations via `patch.object`/`MagicMock` (for example `tests/unit/connectors/test_openai_codex.py`).

**What NOT to Mock:**
- Do not mock expected domain transformation behavior; verify actual resulting models/messages (for example `tests/unit/core/services/test_request_transform_pipeline.py`).
- For true network integration tests, bypass global backend mocking intentionally and execute against real services when credentials exist (for example `tests/integration/test_gemini_end_to_end.py`).

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    env = {"APP_HOST": "localhost", "OPENAI_API_KEY": "test_openai_key", ...}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return env
```
- Pattern source: `tests/conftest.py`.

**Location:**
- Shared fixtures/hooks: `tests/conftest.py`.
- Scope-specific fixtures: `tests/unit/conftest.py`, `tests/integration/conftest.py`, `tests/property/conftest.py`.
- Reusable property generators/helpers: `tests/utils/property_test_generators.py`, `tests/utils/hypothesis_config.py`, `tests/utils/property_test_helpers.py`.

## Coverage

**Requirements:**
- No enforced minimum threshold detected (`[tool.coverage.*]` config exists in `pyproject.toml`, but no `fail_under` setting).

**View Coverage:**
```bash
./.venv/Scripts/python.exe -m pytest --cov=src --cov-report=term-missing --cov-report=xml
```

## Test Types

**Unit Tests:**
- Scope: domain/services/connectors in isolation with fixture-driven setup and mocked I/O boundaries.
- Locations: `tests/unit/**` (for example `tests/unit/core/services/test_request_transform_pipeline.py`).

**Integration Tests:**
- Scope: multi-component flows, app wiring, command flow snapshots, and selected real-network scenarios.
- Locations: `tests/integration/**` (for example `tests/integration/commands/test_integration_help_command.py`, `tests/integration/test_gemini_end_to_end.py`).

**E2E Tests:**
- Framework: pytest-based subprocess/system-level flows (no separate Cypress/Playwright framework detected).
- Example: booting uvicorn + running client subprocess in `tests/integration/test_gemini_end_to_end.py`.

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_...():
    result = await service_call(...)
    assert result is not None
```
- Common across `tests/unit/**` and `tests/integration/**`; collection/runtime behavior is customized in `tests/conftest.py`.

**Error Testing:**
```python
with pytest.raises(ValueError, match="file not found"):
    hydrate_auto_append_first_prompt(cfg)
```
- Pattern source: `tests/unit/core/config/test_auto_append_first_prompt.py`.

**Property-Based Testing:**
```python
@pytest.mark.asyncio
@given(chunks=chunk_stream_strategy(min_size=2, max_size=8))
@property_test_settings()
async def test_property_...(...):
    ...
```
- Pattern sources: `tests/property/test_streaming_async_properties.py`, `tests/utils/hypothesis_config.py`.

**Snapshot Testing:**
- Use `pytest-snapshot` fixture `snapshot.assert_match(...)` in test files (for example `tests/integration/commands/test_integration_help_command.py`).
- Snapshot artifacts are stored under `tests/integration/commands/__snapshots__/`.

---

*Testing analysis: 2026-04-04*
