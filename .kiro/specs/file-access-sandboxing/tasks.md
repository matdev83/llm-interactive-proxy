# Implementation Plan

- [ ] 1. Create configuration
  - Add `--enable-sandboxing` CLI flag in `src/core/cli.py`
  - Support `ENABLE_SANDBOXING` env var
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Implement PathValidationService
  - Implement `normalize_path()`: expand `~`, resolve `..`, handle symlinks
vice.py`

- Implement `normalize_path()`: expand `~`, resolve `..`, handle symlinks
- Implement `is_within_boundary()`: use `Path.relative_to()`
- Implement `extract_paths()`: extract from common param names
- _Requirements: 4.1, 4.2, 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 3. Implement FileSandboxingHandler

  - Create `FileSandboxingHandler` in
 `src/core/services/file_sandboxing_handler.py`
  - Compile tool patterns from config

  - Implement `handle()` method: check tool name, extract paths, validate, block if needed
  - Set `context.blocked` and `context.block_reason` for violations

  - Log blocked operations
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 6.1, 6.2_

- [x] 4. Register handler

  - Add `_register_sandboxing_handler()` in `src/c
ore/app/application_builder.py`
  - Register with tool call reactor at priority 80
  --_Requirements: 1.5, 2.1_
ured
  --_Requirements: 1.5, 2.1_

- [x] 5. Update documentation

  - Add sandboxing section to README.md with config examples

  - _Requirements: 1.1, 1.2, 1.3_

- [x] 6. Write extensive suite of tests

  - Unit tests for PathValidationService (normalization, boundary checks, path extraction)
  - Unit tests for FileSandboxingHandler (tool matching, blocking logic)
  - Integration tests (end-to-end with real tool calls, cross-platform paths)

  - _Requirements: 3.1, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2_
