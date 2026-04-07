# 03-01 Summary - Resilience Retry Standardization

## Scope Completed

- Verified `stamina>=25.2.0` is already present in `pyproject.toml` (no dependency edit was required).
- Implemented canonical retry-after extraction in `src/core/services/resilience/retry_after.py`:
  - direct details fields (`retry_after_seconds`, `retry_after`, `retryAfter`)
  - retry-after headers
  - Google `RetryInfo.retryDelay` and `ErrorInfo.metadata.quotaResetDelay`
  - message-derived duration fallbacks
  - `reset_at` timestamp handling
- Implemented shared stamina-backed async retry abstraction in `src/core/services/resilience/retry_policy.py`:
  - `RetryPolicy`
  - `RetryBudget`
  - `RetryAttemptRecord`
  - `AsyncRetryExecutor`
- Updated `src/core/services/failure_handling_strategy.py` to delegate retry-after parsing to the canonical extractor.

## Connector Migrations

- **Codex (`src/connectors/openai_codex/executor.py`)**
  - auth retry delays are delegated to shared `AsyncRetryExecutor` scheduling
  - direct auth-loop delay sleeping removed
  - visible-output safety guard preserved (do not restart stream after visible output)

- **Gemini (`src/connectors/gemini_base/streaming_executor.py`)**
  - rate-limit wait/retry hotspots now use shared `AsyncRetryExecutor`
  - backend cooldown semantics remain monotonic (only moves forward)
  - retry exhaustion now surfaces serialized retry context in error details

## Tests Added

- `tests/unit/core/services/resilience/test_retry_policy.py`
- `tests/unit/connectors/openai_codex/test_retry_standardization.py`
- `tests/unit/connectors/gemini_base/test_retry_standardization.py`

## Verification Executed

### Per-file quality gates

Ran for each edited Python file:
- `./.venv/Scripts/python.exe -m ruff check --fix <file>` -> PASS
- `./.venv/Scripts/python.exe -m black <file>` -> PASS
- `./.venv/Scripts/python.exe -m mypy <file>` -> PASS

Files:
- `src/core/services/resilience/retry_policy.py`
- `src/core/services/resilience/retry_after.py`
- `src/core/services/failure_handling_strategy.py`
- `src/connectors/openai_codex/executor.py`
- `src/connectors/gemini_base/streaming_executor.py`
- `tests/unit/core/services/resilience/test_retry_policy.py`
- `tests/unit/connectors/openai_codex/test_retry_standardization.py`
- `tests/unit/connectors/gemini_base/test_retry_standardization.py`

### Required plan verification tests

- `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/resilience/test_retry_policy.py -q` -> PASS (`7 passed`)
- `./.venv/Scripts/python.exe -m pytest tests/unit/connectors/openai_codex/test_retry_standardization.py -q` -> PASS (`4 passed`)
- `./.venv/Scripts/python.exe -m pytest tests/unit/connectors/gemini_base/test_retry_standardization.py -q` -> PASS (`4 passed`)
- `./.venv/Scripts/python.exe -m pytest tests/unit/chat_completions_tests/test_rate_limit_wait.py -q` -> PASS (`1 passed`)

### Runtime command

- `./.venv/Scripts/python.exe -m src.core.cli --help` -> PASS (exit code 0)

## Notes

- No temporary debug scripts were introduced by this execution.

