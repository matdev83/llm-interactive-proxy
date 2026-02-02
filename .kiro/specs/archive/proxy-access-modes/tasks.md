# Implementation Plan

- [X] 1. Create access mode configuration models
- [x] 1.1 Create AccessMode enum and AccessModeConfig model
  - Create `src/core/config/models/access_mode.py` with `AccessMode` enum (SINGLE_USER, MULTI_USER)
  - Create `AccessModeConfig` Pydantic model with `mode` field defaulting to SINGLE_USER
  - Add helper methods `is_single_user()` and `is_multi_user()`
  - _Requirements: 1.1, 1.2, 1.3, 10.1, 12.1_

- [x] 1.2 Integrate AccessModeConfig into AppConfig
  - Add `access_mode: AccessModeConfig` field to `AppConfigModel` in `src/core/config/models/app_config_model.py`
  - Ensure default value is `AccessModeConfig()` (defaults to SINGLE_USER)
  - _Requirements: 1.1, 12.1_

- [x] 1.3 Write unit tests for access mode configuration models
  - Test AccessMode enum values
  - Test AccessModeConfig default value is SINGLE_USER
  - Test `is_single_user()` and `is_multi_user()` helper methods
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Add CLI flags for access mode selection
- [x] 2.1 Add access mode flags to ArgumentParserBuilder
  - Add mutually exclusive group for `--single-user-mode` and `--multi-user-mode` flags
  - Add help text explaining the differences between modes
  - Indicate Single User Mode is the default
  - _Requirements: 1.2, 1.3, 13.1, 13.2, 13.3_

- [x] 2.2 Add access mode validation to CliArgsValidator
  - Validate mutual exclusivity of `--single-user-mode` and `--multi-user-mode` flags
  - Raise ValueError with clear error message if both flags are specified
  - _Requirements: 1.4_

- [x] 2.3 Write unit tests for CLI argument parsing and validation
  - Test `--single-user-mode` flag sets mode correctly
  - Test `--multi-user-mode` flag sets mode correctly
  - Test both flags together raises ValueError
  - Test no flags defaults to Single User Mode
  - Test help text includes access mode documentation
  - _Requirements: 1.2, 1.3, 1.4, 13.1, 13.2, 13.3_

- [x] 3. Create access mode applicator for configuration
- [x] 3.1 Create AccessModeApplicator in cli_support/applicators
  - Create `src/core/cli_support/applicators/access_mode_applicator.py`
  - Implement `apply_overrides()` method to set access mode from CLI flags
  - Handle parameter resolution tracking
  - _Requirements: 1.2, 1.3_

- [x] 3.2 Integrate AccessModeApplicator into ConfigurationApplicator
  - Add AccessModeApplicator to the applicator chain in `ConfigurationApplicator`
  - Ensure access mode is applied before backend configuration
  - _Requirements: 1.2, 1.3_

- [x] 3.3 Write unit tests for AccessModeApplicator
  - Test CLI flag overrides config file
  - Test default mode when no flag specified
  - Test parameter resolution tracking
  - _Requirements: 1.2, 1.3_

- [x] 4. Create AccessModeValidator service
- [x] 4.1 Create IAccessModeValidator interface
  - Create `src/core/interfaces/access_mode_validator_interface.py`
  - Define `validate(config: AppConfig, args: argparse.Namespace) -> None` method
  - _Requirements: 2.1-2.4, 4.1-4.3, 5.1-5.6, 7.1-7.4, 8.1-8.3, 9.1-9.5_

- [x] 4.2 Implement AccessModeValidator service
  - Create `src/core/services/access_mode_validator.py`
  - Implement Single User Mode localhost validation
  - Implement Multi User Mode authentication enforcement
  - Implement Multi User Mode OAuth flag rejection
  - Implement Multi User Mode OAuth auto-replacement rejection
  - Implement Multi User Mode desktop notification rejection
  - Generate clear, actionable error messages for all validation failures
  - _Requirements: 2.1-2.4, 4.1-4.3, 5.1-5.6, 7.1-7.4, 8.1-8.3, 9.1-9.5, 11.1-11.4_

- [x] 4.3 Write unit tests for AccessModeValidator
  - Test Single User Mode allows localhost
  - Test Single User Mode rejects non-localhost
  - Test Single User Mode allows OAuth flags
  - Test Single User Mode allows notifications
  - Test Multi User Mode allows localhost without auth
  - Test Multi User Mode allows localhost with auth
  - Test Multi User Mode allows non-localhost with auth
  - Test Multi User Mode rejects non-localhost without auth
  - Test Multi User Mode rejects OAuth debugging override flags
  - Test Multi User Mode rejects `--allow-oauth-auto-replacement`
  - Test Multi User Mode rejects desktop notifications
  - Test error messages contain actionable guidance
  - Test error messages reference relevant CLI flags
  - _Requirements: 2.1-2.4, 4.1-4.3, 5.1-5.6, 7.1-7.4, 8.1-8.3, 9.1-9.5, 11.1-11.4_

- [x] 4.4 Write property test for Single User Mode localhost enforcement
  - **Property 1: Single User Mode localhost enforcement**
  - **Validates: Requirements 2.2**
  - Generate random non-localhost IP addresses
  - Verify all fail validation in Single User Mode
  - _Requirements: 2.2_

- [x] 4.5 Write property test for Multi User Mode auth enforcement
  - **Property 2: Multi User Mode authentication enforcement for non-localhost**
  - **Validates: Requirements 5.4**
  - Generate random non-localhost IP addresses with auth disabled
  - Verify all fail validation in Multi User Mode
  - _Requirements: 5.4_

- [x] 4.6 Write property test for Multi User Mode non-localhost with auth
  - **Property 3: Multi User Mode allows non-localhost with authentication**
  - **Validates: Requirements 5.3**
  - Generate random non-localhost IP addresses with auth enabled
  - Verify all pass validation in Multi User Mode
  - _Requirements: 5.3_

- [x] 4.7 Write property test for Multi User Mode OAuth flag blocking
  - **Property 4: Multi User Mode blocks OAuth debugging override flags**
  - **Validates: Requirements 7.1**
  - Test all known OAuth debugging override flags
  - Verify all fail validation in Multi User Mode
  - _Requirements: 7.1_

- [x] 4.8 Write property test for error message quality
  - **Property 5: Error messages provide actionable guidance**
  - **Validates: Requirements 11.2**
  - Generate various validation failures
  - Verify all error messages contain actionable guidance
  - _Requirements: 11.2_

- [x] 4.9 Write property test for error message CLI flag references
  - **Property 6: Error messages reference relevant CLI flags**
  - **Validates: Requirements 11.3**
  - Generate access mode validation failures
  - Verify all error messages reference relevant CLI flags
  - _Requirements: 11.3_

- [x] 4.10 Write property test for validation exit codes
  - **Property 7: Validation failures exit with non-zero code**
  - **Validates: Requirements 11.4**
  - Generate various validation failures
  - Verify all exit with non-zero code
  - _Requirements: 11.4_

- [x] 5. Integrate AccessModeValidator into startup sequence
- [x] 5.1 Add validation call to ServerLifecycleManager
  - Call `AccessModeValidator.validate()` after config loading
  - Call before backend connector loading
  - Handle ValidationError and exit with non-zero code
  - _Requirements: 2.1-2.4, 4.1-4.3, 5.1-5.6, 7.1-7.4, 8.1-8.3, 9.1-9.5, 11.4_

- [x] 5.2 Add access mode logging during startup
  - Log selected access mode at INFO level
  - Include access mode in startup banner/summary
  - _Requirements: 1.5, 10.1, 10.2_

- [x] 5.3 Write integration tests for startup validation
  - Test Single User Mode startup succeeds with localhost
  - Test Single User Mode startup fails with non-localhost
  - Test Multi User Mode startup succeeds with localhost
  - Test Multi User Mode startup succeeds with non-localhost and auth
  - Test Multi User Mode startup fails with non-localhost without auth
  - Test Multi User Mode startup fails with OAuth flags
  - Test Multi User Mode startup fails with notifications
  - _Requirements: 2.1-2.4, 5.1-5.6, 7.1-7.4, 8.1-8.3, 9.1-9.5_

- [x] 6. Implement OAuth connector filtering
- [x] 6.1 Create OAuth connector detection utilities
  - Create `src/connectors/oauth_detector.py`
  - Implement `is_oauth_connector(module_name: str) -> bool` function
  - Check naming patterns (`-oauth-`, `-oauth`)
  - Check `has_static_credentials` property if connector is loaded
  - Maintain explicit list of known OAuth connectors
  - _Requirements: 6.1, 6.2_

- [x] 6.2 Enhance connector auto-discovery with OAuth filtering
  - Modify `src/connectors/__init__.py` to check access mode
  - Skip OAuth connectors during import in Multi User Mode
  - Log skipped OAuth connectors at INFO level with count
  - Log loaded OAuth connectors at DEBUG level in Single User Mode
  - _Requirements: 6.1, 6.2, 6.3, 10.4, 10.5_

- [x] 6.3 Write unit tests for OAuth connector detection
  - Test naming pattern detection (`-oauth-`, `-oauth`)
  - Test `has_static_credentials` property check
  - Test known OAuth connector list
  - Test detection of `gemini-oauth-auto`, `anthropic-oauth`, `qwen-oauth`, `openai-codex`
  - _Requirements: 6.1, 6.2_

- [x] 6.4 Write integration tests for OAuth connector filtering
  - Test Single User Mode loads all connectors including OAuth
  - Test Multi User Mode skips OAuth connectors
  - Test Multi User Mode logs skipped connector count
  - Test backend registry does not contain OAuth connectors in Multi User Mode
  - Test requests to OAuth connectors fail in Multi User Mode
  - _Requirements: 3.1, 3.2, 6.1, 6.2, 6.4, 6.5_

- [x] 7. Update health endpoint to include access mode
- [x] 7.1 Add access mode to health endpoint response
  - Modify health endpoint controller to include `access_mode` field
  - Return current access mode from AppConfig
  - _Requirements: 10.3_

- [x] 7.2 Write integration test for health endpoint
  - Test health endpoint includes `access_mode` field
  - Test field value matches configured mode
  - _Requirements: 10.3_

- [x] 8. Update documentation
- [x] 8.1 Update README.md with access mode documentation
  - Add section explaining Single User Mode vs Multi User Mode
  - Provide usage examples for both modes
  - Explain when to use each mode
  - _Requirements: 13.4_

- [x] 8.2 Update CHANGELOG.md
  - Add entry for new access mode feature
  - Document breaking changes (none, backward compatible)
  - Document new CLI flags
  - _Requirements: 13.4_

- [x] 8.3 Create access mode user guide
  - Create `docs/user_guide/access-modes.md`
  - Document access mode concepts
  - Provide configuration examples
  - Document validation rules and error messages
  - _Requirements: 13.4_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
