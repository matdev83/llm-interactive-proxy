---
phase: 02-compatibility-contract-stabilization
plan: 02
subsystem: connectors/openai
tags: [testing, contracts, openai, streaming, tool-calls, error-handling]
dependency_graph:
  requires: []
  provides: [openai-compat-contract-tests]
  affects: [tests/unit/connectors]
tech_stack:
  added: []
  patterns: [contract-testing, mock-sse-fixtures, exception-adapter-unit-testing]
key_files:
  created:
    - tests/unit/connectors/test_openai_compat_contracts.py
  modified: []
decisions:
  - "Contract tests assert shape via mocked SSE fixtures rather than live HTTP — keeps tests self-contained and fast"
  - "Error shape tests call exception adapter directly as a unit rather than mocking internals"
  - "TDD RED phase was trivially green since tests assert mock fixture shapes — this is expected for pure contract tests"
metrics:
  duration: 3m
  completed: "2026-04-04T12:18:41Z"
  tasks: 2
  files: 1
---

# Phase 02 Plan 02: OpenAI Compat Contract Tests Summary

9 contract tests asserting OpenAI-spec-shaped SSE chunks, tool-call deltas, and error envelopes through the proxy connector layer (COMP-01).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | OpenAI streaming chunk shape contract tests | 104eba36 | tests/unit/connectors/test_openai_compat_contracts.py |
| 2 | OpenAI tool-call and error-shape contract tests | 104eba36 | tests/unit/connectors/test_openai_compat_contracts.py |

## What Was Built

`tests/unit/connectors/test_openai_compat_contracts.py` with two test classes:

**TestOpenAIStreamingContractShape (tests 1-4):**
- Test 1: Streaming chunks have `id`, `object="chat.completion.chunk"`, `choices` list
- Test 2: At least one chunk's `choices[0].delta` has `role`, `content`, or `tool_calls`
- Test 3: Final streaming chunk has `choices[0].finish_reason` set to `"stop"`
- Test 4: Non-streaming response has `id`, `object="chat.completion"`, `choices[0].message.content`, `usage`

**TestOpenAIToolCallAndErrorShapeContracts (tests 5-9):**
- Test 5: Tool-call streaming chunk has `choices[0].delta.tool_calls[0]` with `id`, `type="function"`, `function.name`
- Test 6: Tool-call non-streaming response has `choices[0].message.tool_calls[0]` with `id`, `type`, `function.name`, `function.arguments`
- Test 7: Error envelope has `{error: {message: str, type: str}}` shape
- Test 8: `AuthenticationError` maps to HTTP 401 with `Authentication` in error type
- Test 9: `RateLimitExceededError` maps to HTTP 429 with `RateLimit` in error type

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- `tests/unit/connectors/test_openai_compat_contracts.py` — FOUND
- Commit `104eba36` — FOUND
- 9/9 tests pass
- No existing OpenAI connector tests broken (12 canonical tests still pass)
