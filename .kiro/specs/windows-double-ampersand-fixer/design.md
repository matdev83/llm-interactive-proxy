# Design Document: Windows Double-Ampersand Command Fixer

## Overview

The Windows Double-Ampersand Command Fixer is a transparent argument rewriting component that modifies command execution tool calls on-the-fly to replace Unix-style `&&` command separators with Windows-compatible `;` separators. Unlike steering-based handlers that swallow tool calls and require additional LLM round trips, this feature performs in-place argument modification as the response flows from the backend to the client.

**Core Mechanism**: When a tool call response is being processed by the middleware pipeline, this feature intercepts command execution tool calls, inspects their arguments for `&&` patterns, replaces them with `;`, and writes the modified arguments back to the response. The client receives the modified tool call without any awareness that modification occurred.

**Key Constraint**: This feature must NOT modify file editing tool calls, as replacing `&&` in source code or configuration files would cause data corruption.

The design reuses patterns from the existing `DangerousCommandHandler` for tool name matching and argument extraction, but instead of swallowing tool calls, it performs transparent argument rewriting similar to `_maybe_fix_droid_antigravity_path` in `ToolCallReactorFeature`.

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     LLM Proxy Pipeline                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         Tool Call Reactor Feature                       │ │
│  │  (Response processing with tool call detection)         │ │
│  └────────────────────────────────────────────────────────┘ │
│                          │                                   │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │   Windows Double-Ampersand Fixer                       │ │
│  │   (Inline argument rewriting, NOT a swallowing handler)│ │
│  │                                                         │ │
│  │  1. Check if client_os contains "win"                  │ │
│  │  2. Check if tool_name matches command execution tool  │ │
│  │  3. Extract command string from arguments              │ │
│  │  4. Replace && with ; in command string                │ │
│  │  5. Write modified arguments back to response          │ │
│  └────────────────────────────────────────────────────────┘ │
│                          │                                   │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         Client Agent (receives modified tool call)     │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Integration Approach

Unlike the `DangerousCommandHandler` which implements `IToolCallHandler` and swallows tool calls, this feature will be integrated as an **inline argument rewriter** within the `ToolCallReactorFeature._process_response` method. This is similar to how `_maybe_fix_droid_antigravity_path` currently works.

The key insight is that `_maybe_fix_droid_antigravity_path` already modifies `tool_arguments` before passing them to handlers. We will add a similar inline call for the double-ampersand fixer.

### Component Interaction Flow

```
Response with tool calls arrives
          │
          ▼
┌─────────────────────────────────────────────────────┐
│ ToolCallReactorFeature._process_response()          │
│                                                      │
│  For each tool call:                                 │
│  1. Extract and parse tool_arguments                │
│  2. Apply _maybe_fix_droid_antigravity_path()       │
│  3. Apply _maybe_fix_windows_double_ampersand()  ◄──┤ NEW
│  4. Create ToolCallContext with modified arguments  │
│  5. Pass to handlers (DangerousCommandHandler, etc) │
│  6. Write modified arguments back to response       │ ◄── CRITICAL
│                                                      │
│  Note: Modified arguments must be written back to   │
│  the response object so client receives changes     │
└─────────────────────────────────────────────────────┘
          │
          ▼
    Client receives response with modified tool call
```

## Components and Interfaces

### 1. WindowsDoubleAmpersandFixer (Service Class)

A standalone service class that encapsulates the replacement logic. This makes the code testable and follows the existing pattern of `DangerousCommandService`.

```python
class WindowsDoubleAmpersandFixer:
    """Service that fixes double-ampersand command separators for Windows clients."""
    
    # Tool names that execute commands (case-insensitive matching)
    COMMAND_EXECUTION_TOOLS: set[str] = {
        "execute",
        "run_command", 
        "bash",
        "shell",
        "terminal",
        "exec",
        "run",
        "execute_command",
        "cmd",
        "powershell",
        "command",
        "run_terminal_command",
        "execute_bash",
        "run_shell",
    }
    
    # Tool names that edit files (must NOT be modified)
    FILE_EDITING_TOOLS: set[str] = {
        "write_file",
        "edit",
        "create",
        "str_replace",
        "patch_file",
        "apply_diff",
        "multiedit",
        "insert_content",
        "replace_lines",
        "replace_in_file",
        "write_to_file",
        "fs_write_text_file",
    }
    
    def __init__(self, enabled: bool = True) -> None:
        """Initialize the fixer.
        
        Args:
            enabled: Whether the feature is enabled (default: True)
        """
        self._enabled = enabled
    
    def is_command_execution_tool(self, tool_name: str) -> bool:
        """Check if tool name matches a command execution tool.
        
        Args:
            tool_name: The name of the tool
            
        Returns:
            True if tool executes commands, False otherwise
        """
    
    def should_process(self, tool_name: str, client_os: str | None) -> bool:
        """Check if this tool call should be processed for && replacement.
        
        Args:
            tool_name: The name of the tool
            client_os: The detected client OS (from session state)
            
        Returns:
            True if tool call should be processed, False otherwise
        """
    
    def fix_command_string(self, command: str) -> tuple[str, bool]:
        """Replace && with ; in a command string.
        
        Args:
            command: The command string to fix
            
        Returns:
            Tuple of (fixed_command, was_modified)
        """
    
    def fix_tool_arguments(
        self, 
        tool_arguments: Any, 
        tool_name: str, 
        client_os: str | None
    ) -> tuple[Any, bool]:
        """Fix double-ampersands in tool arguments if applicable.
        
        Args:
            tool_arguments: The tool arguments (dict, str, or other)
            tool_name: The name of the tool
            client_os: The detected client OS
            
        Returns:
            Tuple of (possibly_modified_arguments, was_modified)
        """
```

### 2. Integration in ToolCallReactorFeature

The fixer will be integrated into `ToolCallReactorFeature._process_response()` after the existing `_maybe_fix_droid_antigravity_path` call.

```python
# In ToolCallReactorFeature._process_response()

# Safety net: auto-fix Droid + Antigravity relative paths
tool_arguments = self._maybe_fix_droid_antigravity_path(
    tool_arguments=tool_arguments,
    backend_name=backend_name,
    calling_agent=calling_agent,
)

# NEW: Fix double-ampersand for Windows clients
tool_arguments, was_modified = self._maybe_fix_windows_double_ampersand(
    tool_arguments=tool_arguments,
    tool_name=function_payload.get("name", "unknown"),
    client_os=self._get_client_os_from_session(session_id),
)
if was_modified:
    # Write modified arguments back to the response
    self._write_back_modified_arguments(
        response=response,
        tool_call=tool_call,
        new_arguments=tool_arguments,
    )
```

### 3. Session State Access

To access `client_os`, we need to get the session from the session manager. This can be done via the context dict or by injecting the session manager.

**Option A**: Pass `client_os` in the context dict (preferred, less invasive):
```python
# In the middleware that creates the context:
context["client_os"] = session.state.client_os
```

**Option B**: Query session manager (more complex, requires dependency):
```python
# In ToolCallReactorFeature:
session = await self._session_manager.get_session(session_id)
client_os = session.state.client_os if session else None
```

**Recommendation**: Use Option A (context dict) as it's simpler and the context is already passed through the pipeline.

### 4. Argument Write-Back Mechanism

The critical part is writing modified arguments back to the response. This requires modifying the `function_payload` in the tool call dict and potentially re-serializing if the response uses string format.

```python
def _write_back_modified_arguments(
    self,
    response: Any,
    tool_call: dict[str, Any],
    new_arguments: Any,
) -> None:
    """Write modified arguments back to the response object.
    
    Args:
        response: The response object containing the tool call
        tool_call: The tool call dict that was modified
        new_arguments: The new arguments to write back
    """
    function_payload = tool_call.get("function")
    if not isinstance(function_payload, dict):
        return
    
    # Serialize back to string if original was string
    original_args = function_payload.get("arguments")
    if isinstance(original_args, str):
        if isinstance(new_arguments, dict):
            function_payload["arguments"] = json.dumps(new_arguments)
        else:
            function_payload["arguments"] = str(new_arguments)
    else:
        function_payload["arguments"] = new_arguments
```

## Data Models

### Configuration Model

Add to `AppConfig`:

```python
@dataclass
class AppConfig:
    # ... existing fields ...
    
    double_ampersand_fixes_for_windows_enabled: bool = True
    """Whether automatic && to ; replacement is enabled for Windows clients."""
```

### Environment Variables

```
DISABLE_DOUBLE_AMPERSAND_FIXES_FOR_WINDOWS=true|false
```

### CLI Arguments

Add to `src/core/cli.py`:

```python
parser.add_argument(
    "--disable-double-ampersand-fixes-for-windows",
    action="store_true",
    dest="disable_double_ampersand_fixes_for_windows",
    default=False,
    help="Disable automatic && to ; replacement in commands for Windows clients",
)
```

### Config File

```yaml
# config.yaml
session:
  double_ampersand_fixes_for_windows_enabled: true  # default
```

## Correctness Properties

### Property 1: Windows Client Detection

*For any* tool call, if the session's `client_os` contains "win" (case-insensitive), then the system should consider processing the tool call for replacement; if `client_os` is None, empty, or does not contain "win", then no replacement should occur.

**Validates: Requirements 1.1, 1.6**

### Property 2: Command Execution Tool Filtering

*For any* tool call, if the tool name matches a command execution tool pattern, then replacement logic should be applied; if the tool name matches a file editing tool pattern or is unknown, then no replacement should occur.

**Validates: Requirements 2.1-2.5**

### Property 3: Replacement Correctness

*For any* command string containing `&&`, all occurrences should be replaced with `;` while preserving surrounding whitespace.

**Validates: Requirements 1.2, 1.3, 6.1**

### Property 4: No False Positives

*For any* command string containing single `&` but not `&&`, the system should not modify the string.

**Validates: Requirements 6.5**

### Property 5: Argument Write-Back Integrity

*For any* tool call where arguments are modified, the modified arguments must be written back to the response in the same format (string or dict) as the original.

**Validates: Requirements 4.3**

### Property 6: Feature Flag Behavior

*For any* configuration where the feature is disabled, no tool calls should be modified regardless of client OS or tool name.

**Validates: Requirements 3.1-3.6**

### Property 7: Error Handling Safety

*For any* error during processing, the original tool call should be passed through unchanged.

**Validates: Requirements 4.5, 6.4**

## Error Handling

### Error Scenarios

1. **Argument Parsing Errors**
   - Malformed JSON in arguments
   - Handle: Skip replacement, log warning, pass original through
   
2. **Session State Access Errors**
   - Session not found or client_os not accessible
   - Handle: Treat as non-Windows (skip replacement), log debug

3. **Write-Back Errors**
   - Response structure doesn't support modification
   - Handle: Log warning, client receives original arguments

4. **Configuration Errors**
   - Invalid configuration values
   - Handle: Use default (enabled), log warning

### Error Recovery Strategy

All errors should be non-fatal. The fixer follows these principles:

1. **Fail Safe**: If uncertain, pass original tool call through unchanged
2. **Log and Continue**: Log errors but never crash the pipeline
3. **Graceful Degradation**: Feature can be disabled without affecting proxy
4. **No Data Corruption**: Never modify file editing tool calls

## Testing Strategy

### Unit Testing

1. **Command String Replacement**
   - Test single `&&` replacement
   - Test multiple `&&` replacement
   - Test `&&` with various whitespace patterns
   - Test no modification for single `&`
   - Test no modification for `&&&` edge case
   - Test empty and whitespace-only strings

2. **Tool Name Matching**
   - Test all command execution tool names
   - Test all file editing tool names
   - Test case-insensitivity
   - Test unknown tool names (should not match)

3. **Client OS Detection**
   - Test "win32", "Windows", "WIN", "windows 10" patterns
   - Test "linux", "darwin", None, empty string (should not match)

4. **Argument Extraction**
   - Test dict with "command" key
   - Test dict with "cmd" key
   - Test raw string arguments
   - Test nested argument structures

### Integration Testing

1. **End-to-End Flow**
   - Create mock response with tool call containing `&&`
   - Verify client receives modified command with `;`

2. **Feature Flag Testing**
   - Verify disabled flag prevents all modifications
   - Verify configuration precedence (CLI > env > config)

3. **Regression Testing**
   - Ensure file editing tools are never modified
   - Ensure non-Windows clients are never modified

### Property-Based Testing

Use Hypothesis to generate:
- Random command strings with various `&` patterns
- Random tool names
- Random client OS strings

## Implementation Notes

### Tool Name Lists

Command execution tools (must be comprehensive):
- `execute`, `Execute`, `run_command`, `bash`, `shell`, `terminal`
- `exec`, `run`, `execute_command`, `cmd`, `powershell`, `command`
- `run_terminal_command`, `execute_bash`, `run_shell`

File editing tools (must be protected):
- `write_file`, `Edit`, `Create`, `str_replace`, `patch_file`
- `apply_diff`, `multiedit`, `insert_content`, `replace_lines`
- `replace_in_file`, `write_to_file`, `fs_write_text_file`, `fs/write_text_file`

### Replacement Logic

```python
def fix_command_string(self, command: str) -> tuple[str, bool]:
    if not command or not isinstance(command, str):
        return command, False
    
    if "&&" not in command:
        return command, False
    
    # Replace && with ; preserving whitespace
    fixed = command.replace("&&", ";")
    return fixed, True
```

### Performance Considerations

1. **String Operations**: Use simple `str.replace()` which is O(n)
2. **Tool Name Lookup**: Use set for O(1) membership testing
3. **Early Exit**: Check feature flag and client_os before any processing
4. **No Regex Needed**: Simple string replacement is sufficient

### Logging Strategy

Log levels:
- **INFO**: Modifications made (session_id, tool_name, truncated before/after)
- **DEBUG**: Tool call checked but no modification needed
- **DEBUG**: Tool call skipped due to tool name or client OS
- **WARNING**: Errors during processing

## Dependencies

- **Existing**: `ToolCallReactorFeature`, `ToolCallContext`, session state
- **Existing**: `AppConfig`, CLI argument parsing
- **Existing**: `DangerousCommandService` pattern (for tool name matching)
- **New**: `WindowsDoubleAmpersandFixer` service class
