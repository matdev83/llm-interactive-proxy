# Dependency Map: streaming_contracts.py

This document lists all import sites of `src.core.ports.streaming_contracts` to ensure backward compatibility during refactoring.

## Public Symbols Used

Based on characterization tests and codebase analysis, the following symbols are publicly used:

- `StreamingContent` - Most widely used
- `StopChunkWithUsage` - Used for usage-bearing stop chunks
- `UsageChunkLeakError` - Exception for usage leak prevention
- `IStreamNormalizer` - Interface for stream normalizers
- `BaseStreamNormalizer` - Base class for normalizers
- `IStreamProcessor` - Interface for stream processors
- `IStreamAssembler` - Interface for stream assemblers
- `SentinelManager` - Done marker management
- `StreamingErrorMapper` - Error mapping utility
- `handle_streaming_error` - Async error handler function

## Import Sites (111 files found)

### Test Files
- `tests/unit/core/ports/test_usage_chunk_cbor_replay.py`
- `tests/unit/core/services/streaming/test_content_accumulation_processor.py`
- `tests/unit/test_openai_normalizer_contract.py`
- `tests/property/test_streaming_async_properties.py`
- `tests/utils/property_test_helpers.py`
- `tests/unit/test_streaming_tool_call.py`
- `tests/utils/property_test_generators.py`
- `tests/unit/test_streaming_contracts_properties.py`
- `tests/unit/test_streaming_processors_properties.py`
- `tests/unit/test_sse_assembler_properties.py`
- `tests/unit/test_streaming_orchestrator_ignored_exit.py`
- `tests/unit/test_streaming_orchestrator_aclose.py`
- `tests/unit/test_response_adapters_properties.py`
- `tests/unit/test_sse_assembler_unit.py`
- `tests/unit/test_observability_properties.py`
- `tests/unit/test_performance_properties.py`
- `tests/unit/streaming/test_streaming_sse_serialization.py`
- `tests/unit/streaming/test_streaming_dict_chunk_passthrough.py`
- `tests/unit/ports/test_streaming_content_whitespace.py`
- `tests/unit/streaming/test_response_adapter_dict_handling.py`
- `tests/unit/loop_detection/test_session_isolation.py`
- `tests/unit/json_repair_processor_test.py`
- `tests/unit/core/services/test_steering_content_reset.py`
- `tests/unit/core/services/test_response_processor_angel.py`
- `tests/unit/core/services/test_response_processor_service.py`
- `tests/unit/core/services/test_loop_breaking_service.py`
- `tests/unit/core/services/test_middleware_content_preservation.py`
- `tests/unit/core/services/test_json_repair_processor.py`
- `tests/unit/core/services/test_edit_precision_response_middleware.py`
- `tests/unit/core/services/streaming/test_usage_tracking_wrapper.py`
- `tests/unit/core/services/streaming/test_vtc_postprocessor.py`
- `tests/unit/core/services/streaming/test_stream_formatting_service.py`
- `tests/unit/core/services/streaming/test_vtc_preprocessor.py`
- `tests/unit/core/services/streaming/test_stream_isolation.py`
- `tests/unit/core/services/streaming/test_middleware_application_processor.py`
- `tests/unit/core/services/streaming/test_tool_call_repair_buffer.py`
- `tests/unit/core/services/streaming/test_stream_normalizer_callback.py`
- `tests/unit/core/services/streaming/test_content_accumulation_buffer_limit.py`
- `tests/unit/core/services/streaming/test_content_accumulation_fix.py`
- `tests/unit/core/ports/test_usage_chunk_leak_prevention.py`
- `tests/unit/core/ports/test_streaming_error_propagation.py`
- `tests/unit/connectors/test_streaming_utils.py`
- `tests/property/test_streaming_middleware_properties.py`
- `tests/regression/test_stop_chunk_wrapper_preservation.py`
- `tests/property/test_text_content_preservation_properties.py`
- `tests/property/test_usage_data_preservation_properties.py`
- `tests/property/test_streaming_sentinel_properties.py`
- `tests/property/test_streaming_content_roundtrip.py`
- `tests/property/test_streaming_error_properties.py`
- `tests/property/test_streaming_contract_properties.py`
- `tests/property/test_stop_chunk_with_usage_properties.py`
- `tests/property/test_content_accumulation_properties.py`
- `tests/property/core/test_usage_tracking_wrapper_properties.py`
- `tests/integration/test_vtc_roundtrip.py`
- `tests/integration/test_windows_double_ampersand_streaming_propagation.py`
- `tests/integration/test_loop_breaking_integration.py`
- `tests/integration/test_loop_detection_session_isolation_e2e.py`
- `tests/integration/test_json_repair_pipeline.py`
- `tests/integration/test_empty_response_prevention.py`
- `tests/integration/test_expected_json_gate.py`
- `tests/integration/test_edit_precision_e2e_di.py`
- `tests/integration/test_antigravity_backend.py`
- `tests/unit/test_tool_call_extra_content_sanitization.py`
- `tests/unit/test_sse_assembler_disconnection.py`
- `tests/unit/test_gemini_normalizer_contract.py`
- `tests/unit/test_anthropic_normalizer_contract.py`
- `tests/unit/core/ports/test_streaming_error_leakage.py`
- `tests/unit/core/ports/test_sse_assembler_keepalive.py`

### Source Files
- `src/core/ports/openai_normalizer.py`
- `src/core/services/stream_formatting_service.py`
- `src/connectors/gemini_base/streaming_executor.py`
- `src/core/ports/sse_assembler.py`
- `src/core/services/usage_tracking_wrapper.py`
- `src/connectors/qwen_oauth.py`
- `src/core/transport/fastapi/response_adapters.py`
- `src/core/services/streaming/content_accumulation_processor.py`
- `src/core/ports/streaming_orchestrator.py`
- `src/core/ports/gemini_normalizer.py`
- `src/connectors/gemini.py`
- `src/core/services/streaming/json_repair_processor.py`
- `src/core/ports/streaming_integration.py`
- `src/core/services/streaming/vtc_preprocessor.py`
- `src/core/services/streaming/vtc_postprocessor.py`
- `src/core/services/streaming/non_streaming_adapter.py`
- `src/core/ports/streaming_processors.py`
- `src/connectors/utils/reasoning_stream_processor.py`
- `src/core/domain/streaming_response_processor.py`
- `src/core/services/loop_breaking_service.py`
- `src/core/services/response_pipeline.py`
- `src/core/services/streaming/stream_utils.py`
- `src/core/ports/usage_processor.py`
- `src/core/ports/anthropic_normalizer.py`
- `src/core/domain/streaming_content.py`

### Script Files
- `scripts/verify_streaming_fixes.py`
- `scripts/verify_gemini_antigravity_fixes.py`
- `scripts/verify_fix.py`
- `scripts/debug_whitespace_issue.py`
- `scripts/debug_streaming_whitespace.py`
- `scripts/debug_streaming_reproduction.py`
- `scripts/debug_streaming_dict_empty.py`
- `scripts/debug_sse_has_content.py`
- `scripts/debug_full_streaming_pipeline.py`
- `scripts/demo_vtc_integration.py`

## Behavioral Invariants

### Stop-Chunk Usage Protection
- `StopChunkWithUsage` prevents accidental stringification
- Raises `UsageChunkLeakError` on `str()` conversion
- Raises `TypeError` on `json.dumps()` without explicit conversion
- Allows `dict()` conversion and `safe_json_dumps()` method

### SSE Framing
- Done marker must be exactly `b"data: [DONE]\n\n"`
- Stop chunks with usage serialize with usage at top level
- Usage must NOT appear in `delta.content`
- Output ends with done marker

### Done Marker Handling
- `SentinelManager.create_done_chunk()` creates standardized done chunks
- `SentinelManager.is_done_marker()` detects done markers
- `SentinelManager.format_sse_done()` returns exact bytes

### StreamingContent
- Preserves whitespace-only deltas
- `from_raw()` parses various input formats
- `to_bytes()` serializes to SSE format

### Error Mapping
- `StreamingErrorMapper.map_backend_error()` maps exceptions
- `handle_streaming_error()` returns terminal `StreamingContent` with error metadata

## Notes

- All import sites must continue to work after refactoring
- The compatibility facade must re-export all public symbols
- No breaking changes to public API signatures




