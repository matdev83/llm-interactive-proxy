# Tasks: Windows Double-Ampersand Command Fixer

## Task 1: Create WindowsDoubleAmpersandFixer Service [COMPLETED]

**Priority**: High
**Validates**: Requirements 1.1-1.6, 2.1-2.5, 5.1-5.5, 6.1-6.6
**Status**: COMPLETED

### Description
Create the core service class that encapsulates the double-ampersand replacement logic.

### Subtasks

1.1. Create `src/core/services/windows_double_ampersand_fixer.py`:
   - Define `COMMAND_EXECUTION_TOOLS` set with tool names that execute commands
   - Define `FILE_EDITING_TOOLS` set with tool names that must be protected
   - Implement `is_command_execution_tool(tool_name: str) -> bool`
   - Implement `should_process(tool_name: str, client_os: str | None) -> bool`
   - Implement `fix_command_string(command: str) -> tuple[str, bool]`
   - Implement `fix_tool_arguments(tool_arguments: Any, tool_name: str, client_os: str | None) -> tuple[Any, bool]`
   - Implement `_extract_command_string(arguments: Any) -> str | None` (reuse pattern from DangerousCommandService)

1.2. Add comprehensive docstrings and type hints

1.3. Add logging for modifications and skipped tool calls

### Acceptance Criteria
- [x] Service correctly identifies command execution tools
- [x] Service correctly protects file editing tools
- [x] Service replaces `&&` with `;` in command strings
- [x] Service handles dict arguments with "command" and "cmd" keys
- [x] Service handles raw string arguments
- [x] Service returns `(original, False)` when no modification needed

---

## Task 2: Create Unit Tests for WindowsDoubleAmpersandFixer [COMPLETED]

**Priority**: High
**Validates**: All correctness properties from design.md
**Status**: COMPLETED

### Description
Create comprehensive unit tests for the fixer service before integrating it.

### Subtasks

2.1. Create `tests/unit/core/services/test_windows_double_ampersand_fixer.py`:
   - Test `is_command_execution_tool` with all known tool names
   - Test `should_process` with various client_os values
   - Test `fix_command_string` with single and multiple `&&`
   - Test `fix_command_string` with single `&` (should not modify)
   - Test `fix_command_string` with empty/whitespace strings
   - Test `fix_tool_arguments` with dict containing "command" key
   - Test `fix_tool_arguments` with dict containing "cmd" key
   - Test `fix_tool_arguments` with raw string argument
   - Test `fix_tool_arguments` with nested dict structure
   - Test `fix_tool_arguments` skips file editing tools
   - Test `fix_tool_arguments` skips non-Windows clients

2.2. Add property-based tests using Hypothesis:
   - Random command strings with various `&` patterns
   - Random tool names (command vs file editing vs unknown)
   - Random client_os strings

### Acceptance Criteria
- [x] 100% test coverage of service class
- [x] All edge cases covered
- [x] Property-based tests validate correctness properties

---

## Task 3: Add Configuration Support [COMPLETED]

**Priority**: High
**Validates**: Requirements 3.1-3.6
**Status**: COMPLETED

### Description
Add CLI flag, environment variable, and config file support for enabling/disabling the feature.

### Subtasks

3.1. Update `src/core/config/app_config.py`:
   - Add `double_ampersand_fixes_for_windows_enabled: bool = True` field

3.2. Update `src/core/cli.py`:
   - Add `--disable-double-ampersand-fixes-for-windows` CLI argument
   - Ensure CLI flag overrides other configuration sources

3.3. Update config loading to handle environment variable:
   - `DOUBLE_AMPERSAND_FIXES_FOR_WINDOWS_ENABLED=true|false`

3.4. Update `config/schemas/app_config.schema.yaml` with the new setting

3.5. Create unit tests for configuration precedence:
   - Test CLI overrides env var
   - Test env var overrides config file
   - Test default is enabled

### Acceptance Criteria
- [x] CLI flag works correctly
- [x] Environment variable works correctly
- [x] Config file setting works correctly
- [x] Precedence is correct: CLI > env > config
- [x] Default is enabled when not explicitly set

---

## Task 4: Integrate with ToolCallReactorFeature [COMPLETED]

**Priority**: High
**Validates**: Requirements 4.1-4.5
**Status**: COMPLETED

### Description
Integrate the fixer into the tool call reactor middleware so it modifies arguments on-the-fly.

### Subtasks

4.1. Update `src/core/services/tool_call_reactor_middleware.py`:
   - Add import for `WindowsDoubleAmpersandFixer`
   - Create fixer instance based on configuration
   - Add call to `fix_tool_arguments` after `_maybe_fix_droid_antigravity_path`
   - Implement `_write_back_modified_arguments` to update response

4.2. Update `src/core/di/services.py`:
   - Inject fixer with configuration into `ToolCallReactorFeature`

4.3. Ensure `client_os` is available in context:
   - Passed from session state via context dict

### Acceptance Criteria
- [x] Fixer is called during response processing
- [x] Modified arguments are written back to response
- [x] Client receives modified tool call with `;` instead of `&&`
- [x] File editing tools pass through unchanged
- [x] Non-Windows clients pass through unchanged
- [x] Feature respects configuration flag

---

## Task 5: Add Logging and Observability [COMPLETED]

**Priority**: Medium
**Validates**: Requirements 7.1-7.5
**Status**: COMPLETED

### Description
Add comprehensive logging for debugging and observability.

### Subtasks

5.1. Add INFO-level logging when modification occurs:
   - Session ID
   - Tool name
   - Original command (truncated to 200 chars)
   - Modified command (truncated to 200 chars)

5.2. Add DEBUG-level logging:
   - When tool call is checked but no modification needed
   - When tool call is skipped due to tool name filtering
   - When tool call is skipped due to non-Windows client OS

5.3. Add WARNING-level logging:
   - When errors occur during processing

5.4. Create tests to verify logging behavior

### Acceptance Criteria
- [x] INFO logs show modifications with relevant details
- [x] DEBUG logs show skip reasons
- [x] WARNING logs show errors
- [x] Long commands are truncated in logs

---

## Task 6: Create User Documentation [COMPLETED]

**Priority**: Medium
**Validates**: Requirements 8.1-8.5
**Status**: COMPLETED

### Description
Create user-facing documentation explaining the feature.

### Subtasks

6.1. Create `docs/user_guide/features/windows-double-ampersand-fixer.md`:
   - Explain the problem (Linux-trained LLMs vs Windows clients)
   - List configuration options (CLI, env var, config file)
   - Explain which tool calls are affected
   - Explain which tool calls are protected
   - Provide before/after command examples

6.2. Update any relevant index or navigation files

### Acceptance Criteria
- [x] Documentation explains the problem and solution
- [x] All configuration options are documented
- [x] Examples are clear and helpful
- [x] Protected tool calls are listed

---

## Task 7: Run Full Test Suite and Verify No Regressions [COMPLETED]

**Priority**: High
**Validates**: All requirements (regression testing)
**Status**: COMPLETED

### Description
Run the complete test suite to ensure no regressions were introduced.

### Subtasks

7.1. Run unit tests: `./.venv/Scripts/python.exe -m pytest tests/unit/`
7.2. Run integration tests: `./.venv/Scripts/python.exe -m pytest tests/integration/`
7.3. Run linting: `./.venv/Scripts/python.exe -m ruff check --fix .`
7.4. Run formatting: `./.venv/Scripts/python.exe -m black .`
7.5. Run type checking: `./.venv/Scripts/python.exe -m mypy src/`

### Acceptance Criteria
- [x] All existing tests pass (6540 passed)
- [x] No new linting errors
- [x] No new type checking errors
- [x] Code is properly formatted
