# OpenAI OAuth Connector Refactor Plan

Goal: reorganize the `openai-oauth` backend into a client-agnostic, capability-driven connector that can serve Codex CLI, generic Chat Completion agents (e.g., Droid/OpenCode), and structured tool-call agents without bespoke code paths.

---

## Phase 0 – Foundations / Analysis
1. **Inventory current behavior**  
   - Document the existing translation layers, prompt injection points, and tool rendering logic (surrounding `src/connectors/openai_oauth.py`, `src/core/domain/translation.py`, `src/core/services/translation_service.py`).  
   - Capture the current detection mechanisms for Kilo/Cline forks and how they influence translation.
2. **Define capability schema**  
   - Draft the capability keys (`protocol`, `tool_text_format`, `prompt_mode`, `tool_schema_mode`, etc.) and default precedence rules described in the PRD.
3. **Decide minimal Codex prompt/tool schema**  
   - Determine the baseline instructions and tool schema we must retain for backend compatibility when clients do not supply their own.

Deliverable: validated assumptions + finalized capability schema design.

---

## Phase 1 – Decouple Kilo-specific logic (Completed)
1. **Audit and remove hard-coded Kilo/Cline branches**  
   - Identify code paths that reference Kilo-specific tool text (e.g., shell `<execute_command>` strings) or rely on agent detection flags.  
   - Replace with generic hooks that defer to capability settings (e.g., XML renderer).
2. **Introduce capability resolver scaffolding**  
   - Add structures to resolve capabilities from request metadata/config without yet implementing all downstream usages.
3. **Ensure default behavior remains functional**  
   - Preserve current functionality (using Kilo renderer) via default capability mapping to avoid regressions prior to completing later phases.

Deliverable: connector no longer depends on Kilo-specific code paths; capability resolver skeleton in place.

---

## Phase 2 – Refactor translation pipeline (In Progress)
1. **Frontend adapter isolation**  
   - Extract inbound request normalization into dedicated units (e.g., Chat → Canonical request, Responses → Canonical request) independent of backend handling.
2. **Backend adapter rework**  
   - Implement passthrough detection based on structural cues/capability flag.  
   - Rebuild payload construction to consult capability settings for prompt/tool schema injection.
3. **Stream adapter cleanup**  
   - Ensure streaming translation produces canonical chunks without embedded client text; textual rendering will occur in a later step.

Deliverable: clean separation of frontend normalization, backend payload building, and canonical stream output.

---

## Phase 3 – Capability-driven tool rendering
1. **Renderer registry**  
   - Implement a registry mapping capability keys (e.g., `xml`, `markdown`) to renderer implementations; default to `none`.
2. **Renderer implementations**  
   - Provide at least:  
     - `none`: pure canonical output.  
     - `xml`: replicates current `<execute_command>/<apply_diff>/<view_image>` behavior generically.  
     - Generic summary fallback.
3. **Stream integration**  
   - Hook the chosen renderer into the stream adapter based on resolved capability.  
   - Ensure `tool_calls` metadata remains unchanged and textual content mirrors renderer output.

Deliverable: tool text rendering governed by capabilities, no agent-specific logic in core modules.

---

## Phase 4 – Prompt & tool schema configurability
1. **Prompt provider abstraction**  
   - Allow selection between codex default, merged, or custom prompt per capability/config.  
   - Inject minimal baseline instructions only when needed.
2. **Tool schema provider**  
   - Support default schema, merged schema, or fully custom definitions.  
   - Validate schemas for completeness before sending upstream.
3. **Configuration surface**  
   - Expose environment variables / config entries to set default prompt/tool modes and capability mappings.

Deliverable: operators can fine-tune prompt/tool behavior without modifying code; client-supplied prompts flow through when allowed.

---

## Phase 5 – Testing & validation
1. **Unit tests**  
   - Cover capability resolver, renderer registry, prompt/tool providers, and translation adapters.  
   - Verify XML renderer output matches expectations while canonical `tool_calls` stay intact.
2. **Integration tests**  
   - Scenarios: Codex passthrough, Chat Completion → Responses translation (no textual rendering), Chat Completion with XML renderer, custom prompt schema pass-through.
3. **Regression suite**  
   - Ensure existing tests (e.g., `test_translation_service_responses_api`) still pass with capability-driven infrastructure.

Deliverable: comprehensive automated coverage affirming backward compatibility and new modular behavior.

---

## Phase 6 – Documentation & rollout (POC scope)
1. **Update docs**  
   - Explain capability configuration, prompt/tool override options, renderer choices, passthrough control.  
   - Include upgrade notes for users migrating from Kilo-specific implementation.
2. **Logging/Observability adjustments**  
   - Ensure debug logs state capability decisions, prompt modes applied, passthrough vs translated path.
3. **POC validation**  
   - Run manual tests with Droid/OpenCode clients to confirm general-purpose behavior before tackling advanced features (rate limiting, metrics, etc.).

Deliverable: ready-to-share documentation and POC validation results; baseline reference implementation for future enhancements.

---

