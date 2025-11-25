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

## Streaming Sampler Configuration

The streaming sampler provides bounded request/response sampling for debugging streaming issues.
Configure via environment variables or `AppConfig`:

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `STREAMING_SAMPLER_ENABLED` | `true` | Enable/disable sampling |
| `STREAMING_SAMPLER_RATE` | `0.01` | Probability of sampling a stream (0.0-1.0) |
| `STREAMING_SAMPLER_MAX_SAMPLES` | `100` | Maximum samples retained in memory |

Or in `config.yaml`:

```yaml
session:
  streaming_sampler:
    enabled: true
    sample_rate: 0.05  # Sample 5% of streams
    max_samples: 200
```

The sampler is configured during application startup in the infrastructure stage.

## Recent Enhancements (Nov 2025)

- **Streaming observability.** `StreamingSampler` now captures bounded request/response samples
  directly inside `SSEAssembler`, giving operators insight into the first emitted chunk, terminal
  errors, and fallback sentinels without enabling verbose logging. Configuration is exposed via
  `AppConfig.session.streaming_sampler` with environment variable support.
- **Unified tool-call lifecycle.** Tool call detection, buffering, and processing state is now
  centralized in `StreamingContextRegistry` with `ToolCallBufferState`. The `_already_processed`
  marker is consistently applied across `ToolCallRepairProcessor`, `ToolCallLoopDetectionMiddleware`,
  and `ToolCallReactorMiddleware` to prevent duplicate processing.
- **Shared streaming context.** Processors, middleware, and transport adapters rely on a single
  `StreamingContextRegistry`, which now tracks execute-command fragments, other XML tool buffers,
  JSON repair state, and accumulated metadata so state never drifts between layers.
- **Generalized tool buffering.** The FastAPI adapter buffers `<execute_command>`, `<patch_file>`,
  `<use_mcp_tool>`, `<ask_followup_question>`, and other XML tool tags to ensure clients never
  receive partial tool payloads.
- **Strict DI for streaming processors.** The DI configuration now enforces strict initialization
  for streaming processors - if any processor cannot be created, the application fails fast during
  startup rather than silently falling back to an empty processor list.
- **Accumulated reasoning metadata.** `ContentAccumulationProcessor` emits both the concatenated
  assistant text (`accumulated_content`) and the combined reasoning trace
  (`accumulated_reasoning`) for offline inspection and regression debugging.
- **Credential watcher debouncing.** Gemini OAuth connectors hash the credentials file before
  scheduling reloads and throttle identical filesystem events, eliminating noisy "file modified"
  messages when nothing actually changed.
- **Temporary debug scripts guarded.** `tmp_*.py` files are ignored at the VCS level so ad-hoc
  probes never make it into CI or release branches again.

