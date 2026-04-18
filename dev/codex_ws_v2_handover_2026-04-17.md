# Codex WS v2 Handover - 2026-04-17

## Current conclusion

`openai-codex-v2` is partially working but still not production-clean.

- WS v2 is active.
- `previous_response_id` is used on some turns.
- Real delta-like continuation is attempted.
- Request growth is lower than the earlier broken state.
- But many turns still fall back to bootstrap/replay.
- The dominant remaining problems are:
  - repeated `Empty streaming response retry triggered`
  - repeated `ws_v2_prefix_mismatch`
  - repeated `previous_response_not_found` on attempted continuation

The latest run improved request count and replay size, but did not eliminate the core instability.

## Latest validated run

- Log:
  - `var/logs/proxy-20260417_174528-p800452.log`
- CBOR:
  - `var/wire_captures_cbor/proxy-20260417_174528-p800452.cbor`

## Latest validated facts

From the latest log and CBOR:

- Total Codex backend requests: `36`
- Prior run had `51`, so this is an improvement.
- `previous_response_id` used in `13` requests.
- Request shapes:
  - `bootstrap/replay=23`
  - `continued_with_bootstrap=13`
  - `continued_delta=0`
- Largest replay request now about `149 KB`.
- Earlier problematic run reached about `217 KB`.
- `prompt_cache_key` remained stable.
- `store=False` on all requests.
- Captured reasoning still `medium`, not `low`.

## Important log evidence

### Empty-stream retry still happens

Examples from latest log:

- `var/logs/proxy-20260417_174528-p800452.log:1462`
- `var/logs/proxy-20260417_174528-p800452.log:1542`
- `var/logs/proxy-20260417_174528-p800452.log:1699`
- `var/logs/proxy-20260417_174528-p800452.log:1776`
- `var/logs/proxy-20260417_174528-p800452.log:1915`
- `var/logs/proxy-20260417_174528-p800452.log:2635`

This means the recent fix that marked tool-call emission as meaningful did not fully cover the shape seen by the empty-stream gate in real traffic.

### Prefix mismatch still happens often

Examples:

- `var/logs/proxy-20260417_174528-p800452.log:1448`
- `var/logs/proxy-20260417_174528-p800452.log:1530`
- `var/logs/proxy-20260417_174528-p800452.log:1631`
- `var/logs/proxy-20260417_174528-p800452.log:2453`
- `var/logs/proxy-20260417_174528-p800452.log:2623`

### Continuation miss still causes fallback replay

Examples:

- `var/logs/proxy-20260417_174528-p800452.log:1557`
- `var/logs/proxy-20260417_174528-p800452.log:1558`
- `var/logs/proxy-20260417_174528-p800452.log:1561`
- `var/logs/proxy-20260417_174528-p800452.log:1564`

Same pattern repeats later in the run.

## What was fixed successfully in this phase

### 1. Traceback spam removal

Handled websocket recovery cases no longer dump tracebacks.

Files:

- `src/connectors/openai_websocket_client.py`
- `src/connectors/openai_codex/executor.py`
- `src/core/services/project_directory_resolution_service.py`

Validated in subsequent live logs.

### 2. WS tool-call chunks now mark tool-call emission in metadata

Implemented:

- `src/connectors/openai_codex/executor.py`
  - normalized translated WS tool-call chunks now stamp:
    - `tool_call_emitted=True`
    - `finish_reason="tool_calls"`

- `src/core/services/backend_request_manager/streaming_response_handler.py`
  - empty-stream gate now treats `tool_call_emitted=True` as meaningful

Regression tests added:

- `tests/unit/connectors/openai_codex/test_executor_streaming.py`
- `tests/unit/core/services/test_backend_request_manager_streaming.py`

Validation:

- `pytest tests/unit/connectors/openai_codex/test_executor_streaming.py tests/unit/core/services/test_backend_request_manager_streaming.py`
- Result: `61 passed`

### 3. This fix improved live behavior, but did not finish the job

Observed improvement:

- backend request count decreased from `51` to `36`
- replay payload ceiling decreased from about `217 KB` to about `149 KB`

But empty-stream retries still clearly occur in live traffic.

## Files changed in the latest coding pass

- `src/connectors/openai_codex/executor.py`
- `src/core/services/backend_request_manager/streaming_response_handler.py`
- `tests/unit/connectors/openai_codex/test_executor_streaming.py`
- `tests/unit/core/services/test_backend_request_manager_streaming.py`

## Tests run and passing

- `./.venv/Scripts/python.exe -m pytest tests/unit/connectors/openai_codex/test_executor_streaming.py tests/unit/core/services/test_backend_request_manager_streaming.py`
  - `61 passed`

Per-file QA also passed:

- `ruff --fix`
- `black`
- `mypy`

on the four edited files above.

## Strongest current hypothesis

The root problem is still not pure WS lineage logic.

The live evidence suggests the backend request manager still sees some tool/result turns as effectively empty, despite the metadata marker fix.

That implies one of these:

1. The chunk shape reaching `gate_empty_stream()` is not the same shape covered by the new metadata-based fix.
2. The meaningful chunk is being swallowed, normalized away, or delayed until after the empty-stream decision.
3. The empty-stream retry is being triggered on a turn where only non-text structured output is present, but the actual marker or `finish_reason` is not preserved on the chunk instance that reaches the gate.

## Best next step

Do not start by patching WS lineage again.

Instead:

1. Add instrumentation or a targeted repro around `BackendStreamingResponseHandler.gate_empty_stream()`.
2. Capture the exact `ProcessedResponse.content` and `ProcessedResponse.metadata` for the chunks immediately before each empty-stream retry in live-equivalent tests.
3. Reproduce the real shape in a unit/integration test.
4. Fix that exact shape classification.
5. Only after empty-stream retry churn is gone, re-evaluate whether remaining `ws_v2_prefix_mismatch` is still present.

## Best concrete debugging targets

### Empty-stream path

- `src/core/services/backend_request_manager/streaming_response_handler.py`
- `src/core/services/response_processor_service.py`
- `src/core/transport/fastapi/adapters/streaming/content_converter.py`
- `src/core/domain/translators/responses/streaming.py`

### WS lineage path

- `src/connectors/openai_codex_v2/ws_lineage.py`
- `src/connectors/openai_codex/executor.py`
- `src/connectors/openai_websocket_client.py`

## Useful commands

Inspect latest capture:

```powershell
./.venv/Scripts/python.exe dev/diag_cbor_requests.py var/wire_captures_cbor/proxy-20260417_174528-p800452.cbor
```

Search latest log for remaining failure patterns:

```powershell
Select-String -Path var/logs/proxy-20260417_174528-p800452.log -Pattern 'Empty streaming response retry triggered|ws_v2_prefix_mismatch|previous response not found|Retrying Codex request with full replay after continuation miss'
```

Run the latest directly related test suites:

```powershell
./.venv/Scripts/python.exe -m pytest tests/unit/connectors/openai_codex/test_executor_streaming.py tests/unit/core/services/test_backend_request_manager_streaming.py
```

## Important non-fixes / still true

- `openai-codex` classic backend remains the safe conservative HTTP replay path.
- `openai-codex-v2` still uses shared OAuth/account management as intended.
- `openai-codex-v2` still sends continued requests with bootstrap fields:
  - capture still reports `continued_with_bootstrap`
  - not `continued_delta`
- Model requests in live capture still show reasoning `medium`, not `low`.

## Short status line

Latest state: fewer requests, smaller replays, no traceback spam, but still mixed-mode WS behavior due to unresolved empty-stream retry churn plus continued prefix mismatch.
