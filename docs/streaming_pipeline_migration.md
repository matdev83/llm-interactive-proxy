## Streaming Pipeline Architecture Overview

The proxy now routes **all** streaming traffic through the refactored pipeline described
in `.kiro/specs/streaming-pipeline-refactor`. Every streaming response flows through these
layers in order:

1. **Provider Stream Producer** – backend connector implements `StreamProducer` and yields
   raw provider chunks.
2. **StreamNormalizer Orchestrator** – selects the provider-specific normalizer, applies the
   registered `IStreamProcessor` chain, and emits canonical `StreamingContent`.
3. **Streaming Assemblers** – currently `SSEAssembler` converts canonical chunks into the
   transport format (SSE) with deterministic sentinel management, metrics, and error mapping.
4. **Transport Adapter** – `to_fastapi_streaming_response` wraps the assembled bytes in the
   FastAPI response, preserving streaming semantics without touching provider‐specific logic.

The legacy "pass-through" streaming path has been removed: if the orchestrator cannot be
constructed we emit an error chunk instead of bypassing the new pipeline.

## Final Checklist for Refactor Completion

To verify a deployment is running only the refactored infrastructure:

- `pytest` (or the CI equivalent) is green with the `tests/streaming_regression` suite enabled.
- `src/core/ports/streaming_integration.py` no longer falls back to raw passthrough; failures
  surface as structured streaming errors.
- `src/core/services/response_processor_service.py` is the only entry point for streaming
  responses on the FastAPI side.
- No code references the removed `src/core/ports/streaming.py` module; all imports point to
  `streaming_contracts`.
- `StreamingContent` creation happens exclusively via the normalizers or processors and is
  validated by the property-based tests in `tests/unit/test_streaming_contracts_properties.py`.

## Adding a New Streaming Backend

1. **Implement the Connector**
   - The connector must implement the `StreamProducer` protocol (`stream_completion` returning
     `AsyncIterator[Any]`) and `get_provider_name`.
   - Normalize backend configuration inside the connector – the streaming pipeline expects
     canonical request objects (`ChatRequest`, etc.).

2. **Register the Provider**
   - Add the provider to `create_pipeline_for_provider` so the orchestrator selects the correct
     normalizer and processor chain.
   - Ensure DI registration for any provider-specific processors/services happens in
     `src/core/di/services.py`.

3. **Create/Reuse a Normalizer**
   - Implement `IStreamNormalizer` (often by extending `BaseStreamNormalizer`). The normalizer
     must yield `StreamingContent` with validated metadata.
   - Add contract tests in `tests/unit` verifying chunk parsing, sentinel handling, and tool-call
     extraction.

4. **Wire Processors**
   - Processors should implement `IStreamProcessor` and be registered through DI. Keep processors
     stateless when possible, otherwise implement `reset`.

5. **Add Regression Coverage**
   - Extend `tests/streaming_regression` with an emulator or fixture that mimics the backend’s
     streaming behavior.
   - Update documentation if the provider introduces new metadata or transport requirements.

## Middleware Development Guidelines

- Processors **must not** mutate the original payload irreversibly; any enrichment should happen
  inside `content.metadata`.
- Always guard hot-path logging with `logger.isEnabledFor(TRACE_LEVEL)`.
- Track middleware mutations through `StreamingMetrics.increment_middleware_mutations`.
- Use `StreamingContent` helpers (`is_done`, `is_empty`, `to_bytes`) instead of custom sentinels.
- Always implement `reset` for stateful processors so the orchestrator can reuse instances safely.

## Troubleshooting

| Symptom                                   | Likely Cause                                   | Resolution                                                             |
|-------------------------------------------|------------------------------------------------|------------------------------------------------------------------------|
| Client receives empty stream / `[DONE]` only | Normalizer dropped all chunks due to validation | Run `pytest tests/unit/test_streaming_contracts_properties.py` to reproduce and inspect chunk metadata. |
| Tool calls duplicated                      | Accumulation processor dedupe misconfigured    | Ensure arguments are normalized via `_normalize_tool_call_arguments`. |
| Loop detection fires immediately           | `min_chunks_before_detection` too low for use-case | Pass `min_chunks_before_detection=2` (or higher) when wiring processor. |
| Pipeline creation fails with ValueError    | Missing DI registration for provider processors | Confirm provider is registered in `create_pipeline_for_provider` and DI services. |
| SSE stream ends without `[DONE]`           | Assembler encountered exception before sentinel | Check logs for `SSEAssembler` errors; `handle_streaming_error` should have emitted a structured chunk. |

## Migration Status

- Legacy streaming modules (`src/core/ports/streaming.py`, `app.state` fallbacks) have been
  removed or replaced with compatibility shims that delegate to the new contracts.
- Existing connectors (OpenAI, Anthropic, Gemini) now implement the `StreamProducer` protocol.
- Transport adapters (`src/core/transport/fastapi/response_adapters.py`) exclusively consume
  `StreamingContent` via the normalizer pipeline; no raw SSE passthrough remains.

New service owners should treat this document as the source of truth for extending or modifying
the streaming stack.

