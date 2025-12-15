# Implementation Plan

- [x] 1. Implement BinaryFileEditPolicy core
  - [x] 1.1 Create binary_file_edit_policy.py with ISteeringPolicy implementation
    - Create `src/services/steering/policies/binary_file_edit_policy.py`
    - Implement `BinaryFileEditPolicy` class with `name`, `priority`, and `evaluate` methods
    - Define `BINARY_EXTENSIONS` frozenset with all binary file extensions
    - Define `PATH_PARAMETER_NAMES` tuple for file path extraction
    - Implement `_extract_file_path()` helper method
    - Implement `_is_binary_extension()` helper method with case-insensitive matching
    - Support prompt override from markdown file
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.1-2.10, 4.1_

  - [x] 1.2 Write property test for binary extension detection
    - **Property 1: Binary extensions trigger steering**
    - **Validates: Requirements 1.1**

  - [x] 1.3 Write property test for non-binary extension pass-through
    - **Property 2: Non-binary extensions pass through**
    - **Validates: Requirements 1.2**

  - [x] 1.4 Write property test for disabled policy behavior
    - **Property 3: Disabled policy returns None**
    - **Validates: Requirements 1.3**

  - [x] 1.5 Write property test for path extraction
    - **Property 4: Path extraction from various parameter names**
    - **Validates: Requirements 1.5**

  - [x] 1.6 Write property test for case-insensitive matching
    - **Property 5: Case-insensitive extension matching**
    - **Validates: Requirements 2.10**

- [x] 2. Add configuration support
  - [x] 2.1 Add config fields to AppConfig
    - Add `binary_file_edit_steering_enabled: bool = True` to `ToolCallReactorConfig`
    - Add `binary_file_edit_steering_message: str | None = None` to `ToolCallReactorConfig`
    - _Requirements: 3.3, 3.5_

  - [x] 2.2 Add CLI flag for disabling the feature
    - Add `--disable-binary-file-edit-steering` argument to `argument_parser_builder.py`
    - _Requirements: 3.1_

  - [x] 2.3 Add applicator logic for CLI flag
    - Update `session_applicator.py` to handle `disable_binary_file_edit_steering` flag
    - Ensure CLI > ENV > YAML precedence
    - _Requirements: 3.1, 3.4_

  - [x] 2.4 Write unit tests for configuration
    - Test CLI flag disables policy
    - Test ENV var disables policy
    - Test config file disables policy
    - Test configuration precedence
    - Test default enabled state
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Register policy in SteeringStage
  - [x] 3.1 Update SteeringStage to register BinaryFileEditPolicy
    - Import `BinaryFileEditPolicy` in `steering.py`
    - Add singleton registration in `_register_steering_policies()`
    - Add policy to list in `_register_unified_steering_handler()`
    - Export from `src/services/steering/policies/__init__.py`
    - _Requirements: 4.2, 4.3, 4.5_

  - [x] 3.2 Write unit tests for policy registration
    - Test policy is registered in DI container
    - Test policy is included in UnifiedSteeringHandler policies list
    - Test prompt override loading
    - _Requirements: 4.2, 4.3_

- [x] 4. Checkpoint - Ensure all tests pass
  - All 61 steering tests pass (45 new tests + 16 existing)

- [x] 5. Write comprehensive unit tests
  - [x] 5.1 Write unit tests for binary extension categories
    - Test executable extensions (.exe, .dll, .so, etc.)
    - Test compiled/object file extensions (.o, .obj, .pyc, etc.)
    - Test database extensions (.db, .sqlite, etc.)
    - Test media extensions (.mp3, .mp4, .avi, etc.)
    - Test image extensions (.jpg, .png, .gif, etc.)
    - Test document extensions (.doc, .pdf, etc.)
    - Test archive extensions (.zip, .tar, etc.)
    - Test font extensions (.ttf, .otf, etc.)
    - Test other binary extensions (.dat, .blend, etc.)
    - _Requirements: 2.1-2.9, 5.1_

  - [x] 5.2 Write unit tests for file path extraction
    - Test extraction from various parameter names
    - Test handling of missing path parameter
    - Test handling of empty path
    - Test handling of malformed arguments
    - _Requirements: 1.5, 5.2_

  - [x] 5.3 Write unit tests for tool recognition
    - Test all file editing tools are recognized
    - Test non-file-editing tools are ignored
    - _Requirements: 1.4_

- [x] 6. Final Checkpoint - Ensure all tests pass
  - All 61 steering tests pass successfully
