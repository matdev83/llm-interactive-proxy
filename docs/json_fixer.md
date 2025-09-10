# JSON Repair + Schema Coercion Middleware — Detailed Plan
🎯 Objectives

Automatically detect and repair malformed JSON in model/tool responses.

Optionally validate and coerce data into a target schema (JSON Schema).

Support both non-streaming and streaming pipelines.

Minimize latency and avoid corrupting already-valid JSON.

Provide configurability (strict vs. permissive, schema-aware vs. schema-free).

📦 Scope

Non-streaming: Full string post-processing before downstream consumers.

Streaming: Buffer chunks, detect JSON completion, repair/validate, yield repaired JSON.

Schema Coercion: Using jsonschema with coercion (e.g., "42" → 42).

Integration: As middleware in ResponseProcessor pipeline (similar to ToolCallRepairMiddleware).

🏗️ Architecture & File Layout

src/core/services/json_repair_service.py

Functions for extraction, repair, validation, coercion.

src/core/services/streaming_json_repair_processor.py

Buffers & repairs JSON in streaming mode.

src/core/app/middleware/json_repair_middleware.py

Middleware class (JsonRepairMiddleware) with config injection.

src/core/config/app_config.py

Config keys & env wiring.

src/core/app/stages/core_services.py

Register middleware in pipeline.

⚙️ Configuration

New AppConfig keys (session level):

json_repair_enabled: bool = true

json_repair_buffer_cap_bytes: int = 65536

json_repair_strict_mode: bool = false

json_coercion_enabled: bool = true

json_schema_sources: dict[str, Any] = {} (schema registry)

Env vars:

JSON_REPAIR_ENABLED

JSON_REPAIR_BUFFER_CAP_BYTES

JSON_REPAIR_STRICT_MODE

JSON_COERCION_ENABLED

🧩 Detection & Repair Algorithm

Extraction order:

Prefer fenced ```json blocks.

Otherwise scan for {...} / [...] balanced braces.

Repairs:

Convert ' → " for keys/strings (safe mode).

Remove trailing commas.

Escape stray control characters.

Close unbalanced braces/brackets (non-streaming only).

Trim commentary before/after JSON.

Confidence:

If parseable after repair → accept.

If still invalid:

strict_mode=true → leave untouched.

strict_mode=false → leave untouched but add warning metadata.

📑 Schema Coercion

Library: jsonschema (with type coercion).

Features:

Type coercion ("42"→42, "true"→true).

Defaults injection.

Unknown property handling (respect additionalProperties).

Lookup order:

Tool/function name → schema registry.

Inline schema ID from extra_body.

Default/fallback schema.

🔄 Middleware Behavior
Non-Streaming

Extract candidate JSON.

Attempt repair.

If schema available → validate & coerce.

Replace response.content with repaired JSON string.

Add metadata {repaired, coerced, schema_id}.

Streaming

Maintain buffer (up to json_repair_buffer_cap_bytes).

Accumulate chunks until braces balanced.

Attempt repair + coercion once full JSON assembled.

Emit repaired JSON downstream.

If trailing free text after JSON → strip by default.

📊 Telemetry

Counters:

json_repair_attempts

json_repair_successes

json_coercion_successes

json_repair_fallbacks

Metadata:

{
  "json_repair": {
    "repaired": true,
    "coerced": false,
    "schema_id": "tool.args.v1"
  }
}

🧪 Testing Plan (TDD)

Unit tests:

tests/unit/core/services/test_json_repair_service.py

tests/unit/core/services/test_json_schema_coercion.py

tests/unit/core/services/test_json_repair_middleware.py

tests/unit/core/services/test_streaming_json_repair_processor.py

Scenarios:

Already valid JSON → untouched.

Single quotes, trailing commas, missing brace → repaired.

Schema coercion: type casting, default insertion, unknown property rejection.

Streaming across multiple chunks.

Buffer cap respected.

Strict vs. permissive behavior.

🚀 Rollout Strategy

Phase 1 (safe default):

Enabled, strict_mode=false, coercion enabled.

Only process fenced JSON or expect_json=true.

Phase 2 (expanded):

Handle heuristic detections in free text.

Broader schema registry integration.

Phase 3 (optional future):

Auto-corrective “re-ask” when repair impossible.

🔍 Dependency Analysis

jsonschema — required for validation & coercion.

mangiucugna/json_repair
`:

Pros:

Mature library, covers many JSON quirks (unquoted keys, trailing commas, NaNs).

Actively maintained.

Cons:

Extra dependency → heavier footprint.

May overlap with minimal in-house repair logic.

Recommendation:

✅ Use for non-streaming repair path (saves dev time, robust).

❌ For streaming path, implement lightweight repair (faster, fewer allocations).

📂 Implementation TODOs

 Add jsonschema to pyproject.toml.

 Decide whether to vendor or import json_repair.

 Implement json_repair_service.py with extraction & repair.

 Implement json_repair_middleware.py.

 Implement streaming_json_repair_processor.py.

 Wire config & DI in app_config.py + core_services.py.

 Write TDD tests.

 Add telemetry counters.

 Stage rollout behind config flags.

✅ With this plan, you’ll have a robust JSON repair + schema coercion middleware that works for both non-streaming and streaming cases, integrates cleanly into your pipeline, and provides flexibility for conservative or aggressive repair modes.