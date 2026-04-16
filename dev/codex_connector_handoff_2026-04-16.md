## Codex Connector Handoff - 2026-04-16

This note is for the next session. Treat it as the starting brief and re-verify current working tree state before editing anything.

### Current Situation

The `openai-codex` connector was heavily refactored toward delta-style continuation. A critical diagnostic step then used the vendored Codex source under `dev/thrdparty/codex`, which materially changed the understanding of how continuation is supposed to work.

The key finding is:

- `previous_response_id` is **not** part of the HTTP `/responses` request contract used by Codex.
- It is only part of the websocket v2 `response.create` request shape.
- The real Codex client uses `previous_response_id` only for websocket-v2 incremental continuation with strict prefix matching.
- The HTTP path relies on `prompt_cache_key` and full request bodies, not `previous_response_id`.

This matches the live production symptom already observed:

- second-turn HTTP requests with `previous_response_id` were rejected with `HTTP 400`
- error body: `{"detail":"Unsupported parameter: previous_response_id"}`

### Source-of-Truth Evidence

Vendored Codex source:

- HTTP request model has no `previous_response_id`:
  - [common.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/codex-api/src/common.rs:146)
- Websocket create request does have `previous_response_id`:
  - [common.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/codex-api/src/common.rs:186)
- HTTP -> websocket conversion initializes `previous_response_id` to `None`:
  - [common.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/codex-api/src/common.rs:160)
- Codex core builds HTTP requests with stable `prompt_cache_key` from conversation id:
  - [client.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/core/src/client.rs:560)
- Websocket v2 continuation injects `previous_response_id` only after strict incremental-prefix validation:
  - [client.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/core/src/client.rs:652)
  - [client.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/core/src/client.rs:676)
- Websocket tests proving intended behavior:
  - prefix continuation uses `previous_response_id`:
    - [client_websockets.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/core/tests/suite/client_websockets.rs:1208)
    - [client_websockets.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/core/tests/suite/client_websockets.rs:1240)
  - changed instructions disable `previous_response_id` and force full create:
    - [client_websockets.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/core/tests/suite/client_websockets.rs:1250)
  - error path also clears `previous_response_id` for the next create:
    - [client_websockets.rs](C:/Users/Mateusz/source/repos/llm-interactive-proxy/dev/thrdparty/codex/codex-rs/core/tests/suite/client_websockets.rs:1287)

### Production Evidence Already Seen

Relevant live artifacts:

- [proxy-20260416_093110-p1452.log](C:/Users/Mateusz/source/repos/llm-interactive-proxy/var/logs/proxy-20260416_093110-p1452.log)
- [proxy-20260416_093110-p1452.cbor](C:/Users/Mateusz/source/repos/llm-interactive-proxy/var/wire_captures_cbor/proxy-20260416_093110-p1452.cbor)

Important facts from that run:

- turn 3 was sent as a small continued request
- it included `previous_response_id`
- upstream returned `HTTP 400`
- body said `Unsupported parameter: previous_response_id`

So the connector did succeed in generating a delta-shaped request, but it did so on the wrong transport contract.

### Current Local Working Tree

At the moment this note was written, these files were modified:

- `dev/diag_cbor_requests.py`
- `src/connectors/openai_codex/executor.py`
- `src/core/services/request_processor_service.py`
- `tests/unit/connectors/openai_codex/test_executor_streaming.py`

Do **not** assume all current edits are correct. Re-read before changing anything.

Most suspicious area:

- [executor.py](C:/Users/Mateusz/source/repos/llm-interactive-proxy/src/connectors/openai_codex/executor.py)

There was an in-progress adaptation after discovering the 400. That file likely contains partial logic around `_supports_previous_response_id(...)` and continuation reasons. Re-validate against the vendored Codex source before extending it.

### What Is Probably Wrong Architecturally

The proxy currently tries to emulate websocket-v2 Codex continuation semantics on the HTTP backend path.

That is the wrong model.

For the HTTP Codex path, the correct mental model is probably:

- keep `instructions` present
- keep stable `prompt_cache_key`
- preserve item ids and other cache-relevant fields
- avoid mutating the stable bootstrap unnecessarily
- accept that HTTP `/responses` may still need full `input`
- do **not** send `previous_response_id`

This means the earlier assumption that delta continuation on HTTP should work via `previous_response_id` is almost certainly false.

### What To Fix Next

Use TDD. Start with repro tests before code edits.

#### Wave 1: Correct the contract

1. Remove proxy-managed `previous_response_id` injection from the HTTP Codex execution path.
2. Keep passthrough preservation only if there is a real transport path that legitimately accepts it. If this connector only uses HTTP for `openai-codex`, passthrough should likely reject or strip it as unsupported.
3. Update tests so HTTP-streaming Codex requests do **not** expect `previous_response_id` continuation behavior.

Add/adjust tests in:

- [test_executor_streaming.py](C:/Users/Mateusz/source/repos/llm-interactive-proxy/tests/unit/connectors/openai_codex/test_executor_streaming.py)
- [test_payload.py](C:/Users/Mateusz/source/repos/llm-interactive-proxy/tests/unit/connectors/openai_codex/test_payload.py)
- [test_openai_codex_codex_cli.py](C:/Users/Mateusz/source/repos/llm-interactive-proxy/tests/unit/connectors/test_openai_codex_codex_cli.py)

Expected RED tests:

- HTTP Codex continuation attempt must not place `previous_response_id` in payload
- second turn after prior response id exists must still build a valid HTTP request without `previous_response_id`
- live-error regression test for `Unsupported parameter: previous_response_id`

#### Wave 2: Reframe the quota strategy for HTTP Codex

After removing unsupported continuation, re-evaluate what quota optimization is still possible on HTTP:

1. Keep stable `prompt_cache_key`
2. Preserve all item ids / metadata / item references that may help remote caching
3. Keep `instructions` stable across turns
4. Avoid unnecessary `tools` churn if the backend permits it
5. Verify whether full `input` replay is required on HTTP or whether some safer suffix optimization exists without `previous_response_id`

Important constraint:

- The vendored Codex source does **not** prove that HTTP suffix-only replay is valid.
- Do not assume suffix-only HTTP input is supported unless the server contract or app source proves it.
- The safe default is likely full input replay + prompt cache friendliness.

#### Wave 3: Usage reporting

The user also reported that usage/billing info is not being returned for `openai-codex`.

Investigate after Wave 1, because current incomplete/canceled turns may have masked the root cause.

Start from:

- [proxy-20260415_233205-p608308.cbor](C:/Users/Mateusz/source/repos/llm-interactive-proxy/var/wire_captures_cbor/proxy-20260415_233205-p608308.cbor)
- [proxy-20260415_233205-p608308.log](C:/Users/Mateusz/source/repos/llm-interactive-proxy/var/logs/proxy-20260415_233205-p608308.log)

Questions to answer:

- Does upstream omit usage on incomplete/client_disconnect Codex turns?
- Does the proxy fail to forward usage when it is present?
- Is there a difference between normal completed turns and early-canceled tool turns?

### Likely Acceptance Criteria

The next good state should be:

- no second-turn `HTTP 400` from `previous_response_id`
- Codex sessions remain functional across multiple turns
- request shapes match vendored Codex HTTP expectations
- logging clearly states whether the request is using HTTP replay, websocket-style continuation, or a fallback
- usage reporting behavior is explicitly understood, even if upstream sometimes omits usage for interrupted turns

### Commands To Re-Run

Focused tests first:

```powershell
./.venv/Scripts/python.exe -m pytest tests/unit/connectors/openai_codex/test_executor_streaming.py -q
./.venv/Scripts/python.exe -m pytest tests/unit/connectors/openai_codex/test_payload.py -q
./.venv/Scripts/python.exe -m pytest tests/unit/connectors/test_openai_codex_codex_cli.py -q
```

Then broader connector matrix:

```powershell
./.venv/Scripts/python.exe -m pytest tests/unit/connectors/openai_codex tests/unit/connectors/test_openai_websocket_client.py tests/unit/connectors/test_openai_websocket_boundary_capture.py tests/unit/connectors/test_openai_codex_codex_cli.py -q
```

If Python files are edited, run post-edit QA per file:

```powershell
./.venv/Scripts/python.exe -m ruff check --fix <file>
./.venv/Scripts/python.exe -m black <file>
./.venv/Scripts/python.exe -m mypy <file>
```

For fresh capture inspection:

```powershell
./.venv/Scripts/python.exe dev/diag_cbor_requests.py
```

### Recommended Next-Session Opening Move

1. Read this file.
2. Re-open the vendored Codex sources cited above.
3. Inspect current local edits in `src/connectors/openai_codex/executor.py`.
4. Write failing tests that codify: HTTP Codex must not send `previous_response_id`.
5. Fix the connector to follow the vendored contract.
