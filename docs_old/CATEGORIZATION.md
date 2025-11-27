# docs_old Categorization

This document categorizes files in docs_old/ for migration to the new documentation structure.

## Category A: User Guide Content (Migrate)

These files contain user-facing documentation that should be integrated into the new docs structure:

- **identity-override.md** -> docs/user_guide/features/identity-override.md (already migrated)
- **tool_access_control.md** -> docs/user_guide/features/tool-access-control.md (already migrated)
- **testing.md** -> docs/development_guide/testing.md (already migrated)
- **testing_setup.md** -> docs/development_guide/testing.md (already migrated)

## Category B: Development Guide Content (Migrate)

These files contain developer-facing documentation that should be integrated into the development guide:

- **gemini_code_assist_parameters.md** -> docs/development_guide/backends/gemini.md (reference)
- **gemini_2_5_flash_thinking_compatibility.md** -> docs/development_guide/backends/gemini.md (reference)
- **QWEN_REASONING_EFFORT_FEATURE.md** -> docs/development_guide/backends/qwen.md (reference)
- **zai-max-tokens-implementation.md** -> docs/development_guide/backends/zai.md (reference)

## Category C: Obsolete/Development Artifacts (Ignore)

These files are development artifacts, progress reports, or implementation details that are not needed in the new documentation:

- **codex_kilocode_compatibility.md** - Obsolete compatibility documentation
- **codex_kilocode_error_codes.md** - Obsolete error code reference
- **codex_kilocode_quickstart.md** - Obsolete quickstart
- **CODEX_KILOCODE_README.md** - Obsolete README
- **codex_kilocode_tools.md** - Obsolete tools documentation
- **command-pipeline-migration.md** - Development artifact/migration notes
- **concurrency-hardening-task-list.md** - Development artifact/task list
- **openai_codex.md** - Obsolete OpenAI Codex documentation
- **qwen-oauth-tool-call-fix.md** - Development artifact/bug fix notes
- **refactoring_gemini_code_assist_connectors.md** - Development artifact/refactoring notes
- **streaming_pipeline_migration.md** - Development artifact/migration notes
- **test_skip_guidelines.md** - Development artifact/testing guidelines
- **tool_call_processing_optimization.md** - Development artifact/optimization notes
- **zai-mcp-tool-call-fix.md** - Development artifact/bug fix notes

## Summary

- **Category A (User Guide)**: 4 files (already migrated)
- **Category B (Development Guide)**: 4 files (reference material, already integrated)
- **Category C (Obsolete)**: 15 files (can be archived or deleted)

## Action Items

1. All Category A and B content has already been migrated to the new documentation structure
2. Category C files can be archived or deleted as they are development artifacts
3. No additional migration work is needed
