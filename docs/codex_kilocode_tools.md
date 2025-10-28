# Codex-KiloCode Supported Tools and Limitations

## Overview

This document provides a comprehensive reference for all tools supported by the Codex-KiloCode compatibility layer, including usage examples, parameters, and known limitations.

## Tool Categories

- [File Operations](#file-operations)
- [Search Operations](#search-operations)
- [Command Execution](#command-execution)
- [Editing Operations](#editing-operations)
- [MCP Integration](#mcp-integration)
- [Conversation Control](#conversation-control)

---

## File Operations

### read_file

**Description**: Read the contents of a file.

**XML Syntax**:
```xml
<read_file>path/to/file.py</read_file>
```

**Parameters**:
- `path` (required): Relative path to file within workspace

**Translation**:
- Codex native tool: `read_file`
- Fallback: Proxy-side file read

**Result Format**:
```
[read_file] Result:
<file contents>
```

**Limitations**:
- File must be within workspace (if `restrict_to_workspace: true`)
- File size limited by `max_file_size` configuration (default: 10 MB)
- Binary files may not display correctly

**Example**:
```xml
<read_file>src/main.py</read_file>
```

**Configuration**:
```yaml
translation:
  tools:
    read_file: true
  file_operations:
    restrict_to_workspace: true
    max_file_size: 10485760
```

---

### list_files

**Description**: List contents of a directory.

**XML Syntax**:
```xml
<list_files>
  <path>src</path>
  <recursive>true</recursive>
</list_files>
```

**Parameters**:
- `path` (required): Relative path to directory
- `recursive` (optional): Whether to list recursively (default: false)

**Translation**:
- Codex native tool: `list_dir`
- Fallback: Proxy-side directory listing

**Result Format**:
```
[list_files] Result:
src/
  main.py
  utils.py
  tests/
    test_main.py
```

**Limitations**:
- Directory must be within workspace (if `restrict_to_workspace: true`)
- Large directories may be truncated
- Recursive depth may be limited

**Example**:
```xml
<list_files>
  <path>src</path>
  <recursive>true</recursive>
</list_files>
```

**Configuration**:
```yaml
translation:
  tools:
    list_files: true
  file_operations:
    restrict_to_workspace: true
```

---

### write_to_file

**Description**: Write content to a file (creates or overwrites).

**XML Syntax**:
```xml
<write_to_file>
  <path>src/new_file.py</path>
  <content>
def hello():
    print("Hello, world!")
  </content>
</write_to_file>
```

**Parameters**:
- `path` (required): Relative path to file
- `content` (required): Content to write

**Translation**:
- Proxy-side file write operation

**Result Format**:
```
[write_to_file] Result: Successfully wrote to src/new_file.py
```

**Limitations**:
- File must be within workspace (if `restrict_to_workspace: true`)
- Overwrites existing files without warning
- Content size limited by configuration

**Example**:
```xml
<write_to_file>
  <path>README.md</path>
  <content># My Project

This is a new project.
  </content>
</write_to_file>
```

**Configuration**:
```yaml
translation:
  tools:
    write_to_file: true
  file_operations:
    restrict_to_workspace: true
```

---

### insert_content

**Description**: Insert content at a specific position in a file.

**XML Syntax**:
```xml
<insert_content>
  <path>src/main.py</path>
  <position>10</position>
  <content>
# New comment
  </content>
</insert_content>
```

**Parameters**:
- `path` (required): Relative path to file
- `position` (required): Line number or byte offset
- `content` (required): Content to insert

**Translation**:
- Proxy-side file operation

**Result Format**:
```
[insert_content] Result: Successfully inserted content at line 10 in src/main.py
```

**Limitations**:
- File must exist
- Position must be valid
- File must be within workspace

**Configuration**:
```yaml
translation:
  tools:
    insert_content: true
```

---

### edit_file

**Description**: Edit a file with natural language instructions.

**XML Syntax**:
```xml
<edit_file>
  <path>src/main.py</path>
  <instructions>Add error handling to the main function</instructions>
</edit_file>
```

**Parameters**:
- `path` (required): Relative path to file
- `instructions` (required): Natural language edit instructions

**Translation**:
- Proxy-side file operation with LLM assistance

**Result Format**:
```
[edit_file] Result: Successfully edited src/main.py
```

**Limitations**:
- Requires LLM for instruction interpretation
- May not always produce desired results
- File must be within workspace

**Configuration**:
```yaml
translation:
  tools:
    edit_file: true
```

---

## Search Operations

### codebase_search

**Description**: Search the entire codebase for a pattern.

**XML Syntax**:
```xml
<codebase_search>
  <pattern>def main</pattern>
  <case_sensitive>false</case_sensitive>
</codebase_search>
```

**Parameters**:
- `pattern` (required): Search pattern (regex)
- `case_sensitive` (optional): Case-sensitive search (default: false)

**Translation**:
- Codex native tool: `grep_files`
- Fallback: Proxy-side search

**Result Format**:
```
[codebase_search] Result:
src/main.py:10: def main():
src/cli.py:25: def main(args):
tests/test_main.py:5: def test_main():
```

**Limitations**:
- Large codebases may be slow
- Results may be truncated
- Regex syntax must be valid

**Example**:
```xml
<codebase_search>
  <pattern>class \w+Controller</pattern>
  <case_sensitive>true</case_sensitive>
</codebase_search>
```

**Configuration**:
```yaml
translation:
  tools:
    codebase_search: true
```

---

### search_files

**Description**: Search specific files or patterns for content.

**XML Syntax**:
```xml
<search_files>
  <pattern>TODO</pattern>
  <include>**/*.py</include>
  <exclude>**/tests/**</exclude>
</search_files>
```

**Parameters**:
- `pattern` (required): Search pattern
- `include` (optional): Glob pattern for files to include
- `exclude` (optional): Glob pattern for files to exclude

**Translation**:
- Codex native tool: `grep_files` with filters
- Fallback: Proxy-side filtered search

**Result Format**:
```
[search_files] Result:
src/main.py:15: # TODO: Add error handling
src/utils.py:42: # TODO: Optimize this function
```

**Limitations**:
- Glob patterns must be valid
- Large result sets may be truncated
- Performance depends on file count

**Example**:
```xml
<search_files>
  <pattern>FIXME</pattern>
  <include>src/**/*.py</include>
  <exclude>**/test_*.py</exclude>
</search_files>
```

**Configuration**:
```yaml
translation:
  tools:
    search_files: true
```

---

## Command Execution

### execute_command

**Description**: Execute a shell command.

**XML Syntax**:
```xml
<execute_command>
  <command>python -m pytest tests/</command>
  <working_directory>.</working_directory>
  <timeout>30</timeout>
</execute_command>
```

**Parameters**:
- `command` (required): Command to execute
- `working_directory` (optional): Working directory (default: workspace root)
- `timeout` (optional): Timeout in seconds (default: from config)

**Translation**:
- Codex native tool: `shell` with argument array conversion
- Fallback: Proxy-side command execution

**Result Format**:
```
[execute_command] Result:
Exit code: 0
Output:
============================= test session starts ==============================
collected 10 items

tests/test_main.py ..........                                            [100%]

============================== 10 passed in 0.50s ===============================
```

**Limitations**:
- Only allowed shells can be used (see `allowed_shells` config)
- Commands restricted to workspace (if `restrict_to_workspace: true`)
- Output size limited by `max_output_size` configuration
- Long-running commands may timeout

**Security Considerations**:
- Command injection risk - validate inputs
- Restrict to workspace directory
- Limit allowed shells
- Monitor command execution

**Example**:
```xml
<execute_command>
  <command>git status</command>
</execute_command>
```

**Configuration**:
```yaml
translation:
  tools:
    execute_command: true
  command_execution:
    allowed_shells: ["bash", "sh", "cmd", "powershell"]
    restrict_to_workspace: true
    max_output_size: 1048576
```

---

## Editing Operations

### search_and_replace

**Description**: Search for text and replace it in files.

**XML Syntax**:
```xml
<search_and_replace>
  <path>src/main.py</path>
  <search>old_function_name</search>
  <replace>new_function_name</replace>
  <regex>false</regex>
</search_and_replace>
```

**Parameters**:
- `path` (required): File path or glob pattern
- `search` (required): Text to search for
- `replace` (required): Replacement text
- `regex` (optional): Use regex (default: false)

**Translation**:
- Proxy-side search and replace operation

**Result Format**:
```
[search_and_replace] Result: Replaced 3 occurrences in src/main.py
```

**Limitations**:
- File must be within workspace
- Regex must be valid if enabled
- Large files may be slow

**Example**:
```xml
<search_and_replace>
  <path>src/**/*.py</path>
  <search>print\((.*)\)</search>
  <replace>logger.info(\1)</replace>
  <regex>true</regex>
</search_and_replace>
```

**Configuration**:
```yaml
translation:
  tools:
    search_and_replace: true
```

---

### use_mcp_tool (patch_file)

**Description**: Apply a patch to a file using MCP patch_file tool.

**XML Syntax**:
```xml
<use_mcp_tool>
  <tool_name>patch_file</tool_name>
  <arguments>
    <file>src/main.py</file>
    <diff>
--- a/src/main.py
+++ b/src/main.py
@@ -10,6 +10,7 @@
 def main():
+    print("Starting...")
     process_data()
    </diff>
  </arguments>
</use_mcp_tool>
```

**Parameters**:
- `tool_name`: Must be "patch_file"
- `arguments.file` (required): File to patch
- `arguments.diff` (required): Unified diff format

**Translation**:
- Codex native tool: `apply_patch` (if grammar conversion possible)
- Fallback: Direct MCP server invocation

**Result Format**:
```
[use_mcp_tool] Result: Successfully applied patch to src/main.py
```

**Limitations**:
- Diff must be in unified diff format
- File must exist
- Patch must apply cleanly
- Complex patches may require MCP server

**Example**:
```xml
<use_mcp_tool>
  <tool_name>patch_file</tool_name>
  <arguments>
    <file>README.md</file>
    <diff>
--- a/README.md
+++ b/README.md
@@ -1,3 +1,4 @@
 # My Project
+Version 2.0

 This is my project.
    </diff>
  </arguments>
</use_mcp_tool>
```

**Configuration**:
```yaml
translation:
  tools:
    use_mcp_tool: true
```

---

## MCP Integration

### access_mcp_resource

**Description**: Access a resource from an MCP server.

**XML Syntax**:
```xml
<access_mcp_resource>
  <server>code-analysis-server</server>
  <resource>project-structure</resource>
  <parameters>
    <format>json</format>
  </parameters>
</access_mcp_resource>
```

**Parameters**:
- `server` (required): MCP server name
- `resource` (required): Resource identifier
- `parameters` (optional): Resource-specific parameters

**Translation**:
- Codex native tool: `read_mcp_resource` with parameter renaming

**Result Format**:
```
[access_mcp_resource] Result:
{
  "structure": {
    "src": ["main.py", "utils.py"],
    "tests": ["test_main.py"]
  }
}
```

**Limitations**:
- MCP server must be configured and running
- Resource must exist on server
- Network connectivity required

**Example**:
```xml
<access_mcp_resource>
  <server>documentation-server</server>
  <resource>api-docs</resource>
  <parameters>
    <version>v1</version>
  </parameters>
</access_mcp_resource>
```

**Configuration**:
```yaml
translation:
  tools:
    access_mcp_resource: true
```

---

### use_mcp_tool (generic)

**Description**: Invoke any MCP tool.

**XML Syntax**:
```xml
<use_mcp_tool>
  <tool_name>lint</tool_name>
  <arguments>
    <file>src/main.py</file>
    <strict>true</strict>
  </arguments>
</use_mcp_tool>
```

**Parameters**:
- `tool_name` (required): MCP tool name
- `arguments` (optional): Tool-specific arguments

**Translation**:
- Forward to MCP server with schema translation

**Result Format**:
```
[use_mcp_tool] Result:
Linting completed: 3 warnings, 0 errors
```

**Limitations**:
- MCP server must be configured
- Tool must be available on server
- Schema translation may not support all types

**Example**:
```xml
<use_mcp_tool>
  <tool_name>format</tool_name>
  <arguments>
    <file>src/main.py</file>
    <style>black</style>
  </arguments>
</use_mcp_tool>
```

**Configuration**:
```yaml
translation:
  tools:
    use_mcp_tool: true
```

---

## Conversation Control

### attempt_completion

**Description**: Mark the current task as complete.

**XML Syntax**:
```xml
<attempt_completion>
  <result>Successfully implemented the feature</result>
  <command>python -m pytest</command>
</attempt_completion>
```

**Parameters**:
- `result` (required): Completion message
- `command` (optional): Verification command

**Translation**:
- Proxy-side handling (not forwarded to Codex)

**Result Format**:
```
[attempt_completion] Acknowledged: Task marked as complete
```

**Limitations**:
- Does not actually execute verification command
- Session state updated but no external action taken

**Example**:
```xml
<attempt_completion>
  <result>All tests passing, feature complete</result>
  <command>npm test</command>
</attempt_completion>
```

**Configuration**:
```yaml
translation:
  tools:
    attempt_completion: true
```

---

### ask_followup_question

**Description**: Ask a follow-up question to the user.

**XML Syntax**:
```xml
<ask_followup_question>
  <question>Should I also update the documentation?</question>
</ask_followup_question>
```

**Parameters**:
- `question` (required): Question to ask

**Translation**:
- Proxy-side handling (not forwarded to Codex)

**Result Format**:
```
[ask_followup_question] Acknowledged: Question logged
```

**Limitations**:
- Does not actually prompt user
- Question logged but no response mechanism
- Session state updated

**Example**:
```xml
<ask_followup_question>
  <question>Do you want me to add unit tests for this function?</question>
</ask_followup_question>
```

**Configuration**:
```yaml
translation:
  tools:
    ask_followup_question: true
```

---

## Unsupported Tools

The following KiloCode tools are **NOT supported** by the compatibility layer:

### browser_action

**Reason**: Codex does not support browser automation

**Alternative**: Use `codebase_search` to find relevant code, or describe UI in text

### screenshot

**Reason**: Codex does not support image capture

**Alternative**: Describe UI elements in text

### inspect_site

**Reason**: Codex does not support web scraping

**Alternative**: Use `execute_command` with curl/wget for simple HTTP requests

---

## Known Limitations

### General Limitations

1. **Context Window**: Codex has limited context (8K tokens)
   - Large files may be truncated
   - Long command outputs may be truncated
   - Multiple tool results may exceed context

2. **Performance**: Translation adds latency
   - Detection: <5ms (first request only)
   - Translation: <50ms per tool
   - Proxy-side execution: Varies by operation

3. **Error Handling**: Some errors may not be recoverable
   - Malformed XML cannot be auto-corrected
   - Invalid parameters must be fixed by client
   - Timeout errors require configuration changes

### Tool-Specific Limitations

1. **File Operations**
   - Binary files may not display correctly
   - Large files limited by `max_file_size`
   - Workspace restrictions apply

2. **Command Execution**
   - Only allowed shells supported
   - Output size limited
   - Long-running commands may timeout
   - Security restrictions apply

3. **Search Operations**
   - Large codebases may be slow
   - Results may be truncated
   - Regex complexity limited

4. **MCP Integration**
   - Requires MCP server configuration
   - Network latency affects performance
   - Schema translation may not support all types

### Security Limitations

1. **File Access**: Restricted to workspace by default
2. **Command Execution**: Restricted shells and workspace
3. **Path Traversal**: Prevented by validation
4. **Resource Limits**: File size, output size, timeout limits

---

## Best Practices

### 1. Use Appropriate Tools

Choose the right tool for the task:
- Use `codebase_search` for finding code patterns
- Use `read_file` for reading specific files
- Use `execute_command` for running tests/builds
- Use `search_and_replace` for bulk edits

### 2. Handle Errors Gracefully

Always check for errors:
```xml
<read_file>src/main.py</read_file>
<!-- Check result for error messages -->
```

### 3. Optimize Performance

Minimize tool invocations:
- Batch operations when possible
- Use specific paths instead of recursive searches
- Limit search scope with include/exclude patterns

### 4. Follow Security Best Practices

- Never execute untrusted commands
- Validate file paths before operations
- Use workspace restrictions
- Monitor command execution

### 5. Test Thoroughly

Test tool usage:
- Verify XML syntax
- Check parameter types
- Test error cases
- Monitor performance

---

## Tool Comparison Matrix

| Tool | Codex Native | Proxy Fallback | Performance | Security Risk |
|------|--------------|----------------|-------------|---------------|
| read_file | ✓ | ✓ | Fast | Low |
| list_files | ✓ | ✓ | Fast | Low |
| write_to_file | ✗ | ✓ | Fast | Medium |
| execute_command | ✓ | ✓ | Varies | High |
| codebase_search | ✓ | ✓ | Slow | Low |
| search_files | ✓ | ✓ | Medium | Low |
| search_and_replace | ✗ | ✓ | Medium | Medium |
| use_mcp_tool | Partial | ✓ | Varies | Medium |
| access_mcp_resource | ✓ | ✗ | Fast | Low |
| attempt_completion | ✗ | ✓ | Fast | None |
| ask_followup_question | ✗ | ✓ | Fast | None |

**Legend**:
- ✓ = Supported
- ✗ = Not supported
- Partial = Some features supported

---

## Version History

- **v1.0.0** (2025-10-28): Initial release
  - 11 supported tools
  - File, search, command, editing, MCP, and conversation tools
  - Comprehensive parameter validation
  - Security restrictions
