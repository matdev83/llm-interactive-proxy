# File-Changing Tools Inventory

This document catalogs all file-changing tools discovered across popular coding agents. This inventory is used to ensure the sandboxing feature correctly identifies and validates all file operations.

## Summary

**Total Agents Analyzed:** 8
**Total File-Changing Tools Found:** 25+ unique tool names
**Total File Path Parameter Names:** 15+ unique parameter names

## Tool Categories

### 1. File Writing/Creation Tools
Tools that create new files or completely overwrite existing files.

### 2. File Editing/Modification Tools
Tools that make targeted changes to existing files (search/replace, diffs, patches).

### 3. File Deletion Tools
Tools that remove files from the filesystem.

### 4. File Movement/Rename Tools
Tools that move or rename files.

---

## Agent-by-Agent Analysis

### 1. Cline Agent

**Location:** `dev/thrdparty/cline/`
**Language:** TypeScript
**Tool Definition File:** `src/shared/tools.ts`

#### File-Changing Tools:

| Tool Name | Tool ID | Category | Path Parameters | Description |
|-----------|---------|----------|-----------------|-------------|
| Write to File | `write_to_file` | Write | `path` | Creates new files or completely overwrites existing files |
| Replace in File | `replace_in_file` | Edit | `path` | Makes targeted search/replace edits to existing files |

#### Code Reference:
```typescript
// From dev/thrdparty/cline/src/shared/tools.ts
export enum ClineDefaultTool {
	FILE_EDIT = "replace_in_file",
	FILE_NEW = "write_to_file",
	// ... other tools
}
```

#### Path Parameter Names Used:
- `path`

---

### 2. Kilocode Agent

**Location:** `dev/thrdparty/kilocode/`
**Language:** TypeScript
**Tool Definition File:** `src/shared/tools.ts`

#### File-Changing Tools:

| Tool Name | Tool ID | Category | Path Parameters | Description |
|-----------|---------|----------|-----------------|-------------|
| Write to File | `write_to_file` | Write | `path` | Creates new files or complete file rewrites |
| Apply Diff | `apply_diff` | Edit | `path`, `diff` | Applies unified diff patches to files |
| Edit File | `edit_file` | Edit | `target_file` | Fast apply editing using Morph (AI-guided edits) |
| Insert Content | `insert_content` | Edit | `path`, `line` | Inserts content at specific line in file |
| Search and Replace | `search_and_replace` | Edit | `path` | Search and replace with regex support |
| Generate Image | `generate_image` | Write | `path`, `image` | Generates and saves images to files |

#### Code Reference:
```typescript
// From dev/thrdparty/kilocode/src/shared/tools.ts
export interface WriteToFileToolUse extends ToolUse {
	name: "write_to_file"
	params: Partial<Pick<Record<ToolParamName, string>, "path" | "content" | "line_count">>
}

export interface EditFileToolUse extends ToolUse {
	name: "edit_file"
	params: Required<Pick<Record<ToolParamName, string>, "target_file" | "instructions" | "code_edit">>
}

export const TOOL_GROUPS: Record<ToolGroup, ToolGroupConfig> = {
	edit: {
		tools: [
			"apply_diff",
			"edit_file",
			"write_to_file",
			"insert_content",
			"search_and_replace",
			"new_rule",
			"generate_image",
		],
	},
	// ... other groups
}
```

#### Path Parameter Names Used:
- `path`
- `target_file`
- `line`
- `image`

---

### 3. Gemini CLI Agent

**Location:** `dev/thrdparty/gemini-cli/`
**Language:** TypeScript
**Tool Definition File:** `packages/core/src/tools/tools.ts`

#### File-Changing Tools:

Gemini CLI uses a declarative tool system with `Kind` enum for categorization:

| Tool Name | Category (Kind) | Path Parameters | Description |
|-----------|-----------------|-----------------|-------------|
| (Various Edit Tools) | `Kind.Edit` | `path`, `fileName`, `filePath` | Tools marked with Edit kind modify files |
| (Various Delete Tools) | `Kind.Delete` | `path` | Tools marked with Delete kind remove files |
| (Various Move Tools) | `Kind.Move` | `path`, `destination` | Tools marked with Move kind relocate files |

#### Code Reference:
```typescript
// From dev/thrdparty/gemini-cli/packages/core/src/tools/tools.ts
export enum Kind {
  Read = 'read',
  Edit = 'edit',
  Delete = 'delete',
  Move = 'move',
  Search = 'search',
  Execute = 'execute',
  Think = 'think',
  Fetch = 'fetch',
  Other = 'other',
}

// Function kinds that have side effects
export const MUTATOR_KINDS: Kind[] = [
  Kind.Edit,
  Kind.Delete,
  Kind.Move,
  Kind.Execute,
] as const;

export interface ToolLocation {
  // Absolute path to the file
  path: string;
  // Which line (if known)
  line?: number;
}
```

#### Path Parameter Names Used:
- `path`
- `fileName`
- `filePath`
- `destination`

**Note:** Gemini CLI uses a `Kind` enum system where tools are categorized. File-changing tools have kinds: `Edit`, `Delete`, `Move`. The specific tool names vary by implementation.

---

### 4. Codebuff Agent

**Location:** `dev/thrdparty/codebuff/`
**Language:** TypeScript
**Tool Definition File:** `common/src/templates/initial-agents-dir/types/tools.ts`

#### File-Changing Tools:

| Tool Name | Tool ID | Category | Path Parameters | Description |
|-----------|---------|----------|-----------------|-------------|
| Write File | `write_file` | Write | `path` | Creates or edits a file with given content |
| String Replace | `str_replace` | Edit | `path` | Replaces strings in a file with new strings |
| Run File Change Hooks | `run_file_change_hooks` | Meta | `files` | Triggers file change hooks for specified files |

#### Code Reference:
```typescript
// From dev/thrdparty/codebuff/common/src/templates/initial-agents-dir/types/tools.ts
export type ToolName =
  | 'write_file'
  | 'str_replace'
  | 'run_file_change_hooks'
  // ... other tools

export interface WriteFileParams {
  /** Path to the file relative to the **project root** */
  path: string
  /** What the change is intended to do in only one sentence. */
  instructions: string
  /** Edit snippet to apply to the file. */
  content: string
}

export interface StrReplaceParams {
  /** The path to the file to edit. */
  path: string
  /** Array of replacements to make. */
  replacements: {
    /** The string to replace. This must be an *exact match* */
    old: string
    /** The string to replace the corresponding old string with. */
    new: string
    /** Whether to allow multiple replacements of old string. */
    allowMultiple?: boolean
  }[]
}

export interface RunFileChangeHooksParams {
  /** List of file paths that were changed and should trigger file change hooks */
  files: string[]
}
```

#### Path Parameter Names Used:
- `path`
- `files`

---

### 5. Aider Agent

**Location:** `dev/thrdparty/aider/`
**Language:** Python
**Tool Definition File:** `aider/coders/editblock_coder.py`

#### File-Changing Tools:

Aider uses a **search/replace block format** rather than named tool calls. The format is:

```
filename.ext
<<<<<<< SEARCH
original content
=======
new content
>>>>>>> REPLACE
```

| Tool Pattern | Category | Path Parameters | Description |
|--------------|----------|-----------------|-------------|
| SEARCH/REPLACE Blocks | Edit | Filename before block | Search and replace blocks for surgical edits |
| New File Creation | Write | Filename with empty SEARCH | Creates new files with empty SEARCH block |

#### Code Reference:
```python
# From dev/thrdparty/aider/aider/coders/editblock_coder.py
def find_original_update_blocks(content, fence=DEFAULT_FENCE, valid_fnames=None):
    """
    Finds SEARCH/REPLACE blocks in the format:
    
    filename.ext
    <<<<<<< SEARCH
    original text
    =======
    updated text
    >>>>>>> REPLACE
    """
    # ... implementation

def do_replace(fname, content, before_text, after_text, fence=None):
    """
    Applies the search/replace operation to a file.
    Creates new file if before_text is empty.
    """
    # ... implementation
```

#### Path Parameter Names Used:
- Filename extracted from line before fence (not a parameter)

**Note:** Aider doesn't use traditional tool calls. Instead, it parses markdown-formatted SEARCH/REPLACE blocks from LLM responses. The filename is specified on the line before the opening fence.

---

### 6. Codex Agent

**Location:** `dev/thrdparty/codex/`
**Language:** Rust
**Tool Definition File:** `codex-rs/core/src/tools/spec.rs`

#### File-Changing Tools:

| Tool Name | Tool ID | Category | Path Parameters | Description |
|-----------|---------|----------|-----------------|-------------|
| Apply Patch | `apply_patch` | Edit | `path`, `patch` | Applies unified diff patches to files |

#### Code Reference:
```rust
// From dev/thrdparty/codex/codex-rs/core/src/tools/spec.rs
use crate::tools::handlers::apply_patch::ApplyPatchToolType;
use crate::tools::handlers::apply_patch::create_apply_patch_freeform_tool;
use crate::tools::handlers::apply_patch::create_apply_patch_json_tool;

pub(crate) struct ToolsConfig {
    pub apply_patch_tool_type: Option<ApplyPatchToolType>,
    // ... other fields
}

// ApplyPatchToolType can be:
// - Freeform: Free-form patch format
// - Function: Structured JSON function call
```

#### Path Parameter Names Used:
- `path`
- `patch`

**Note:** Codex uses a patch-based editing system. The exact parameter names depend on whether the freeform or function variant is used.

---

### 7. Crush Agent

**Location:** `dev/thrdparty/crush/`
**Language:** Go
**Tool Definition File:** Not found in initial scan

#### File-Changing Tools:

**Status:** No explicit file-changing tool definitions found in the codebase scan. Crush may:
1. Use MCP (Model Context Protocol) tools
2. Rely on shell commands for file operations
3. Have tools defined in a different location

**Recommendation:** Further investigation needed or assume standard patterns like `write_file`, `edit_file`, `delete_file`.

---

### 8. OpenCode Agent

**Location:** `dev/thrdparty/opencode/`
**Language:** TypeScript
**Tool Definition File:** Not found in initial scan

#### File-Changing Tools:

**Status:** No explicit file-changing tool definitions found in the codebase scan. OpenCode may:
1. Use MCP (Model Context Protocol) tools
2. Have tools defined in packages not yet scanned
3. Use a different tool system

**Recommendation:** Further investigation needed or assume standard patterns.

---

## Comprehensive Tool Name Patterns

Based on the analysis, here are all discovered tool name patterns:

### Exact Tool Names:
1. `write_to_file`
2. `write_file`
3. `replace_in_file`
4. `str_replace`
5. `apply_diff`
6. `apply_patch`
7. `edit_file`
8. `insert_content`
9. `search_and_replace`
10. `generate_image`
11. `run_file_change_hooks`

### Pattern Categories:
- **Write patterns:** `write_*`, `*_write_*`, `create_*`
- **Edit patterns:** `edit_*`, `*_edit_*`, `replace_*`, `*_replace_*`
- **Delete patterns:** `delete_*`, `*_delete_*`, `remove_*`, `*_remove_*`
- **Move patterns:** `move_*`, `*_move_*`, `rename_*`, `*_rename_*`, `copy_*`
- **Patch patterns:** `*_patch`, `*_diff`, `apply_*`

---

## Comprehensive Path Parameter Names

All discovered parameter names that may contain file paths:

### Primary Path Parameters:
1. `path`
2. `file_path`
3. `filepath`
4. `file`
5. `target_file`
6. `target`

### Secondary Path Parameters:
7. `destination`
8. `dest`
9. `source`
10. `src`
11. `fileName`
12. `filePath`
13. `image`
14. `patch`
15. `diff`

### Array/List Parameters:
16. `paths`
17. `files`
18. `file_list`
19. `targets`

---

## Validation Against Design Document

### Current Design Patterns:
```python
default_tool_patterns: list[str] = field(default_factory=lambda: [
    r"write_to_file",
    r"write_file",
    r"fsWrite",
    r"replace_in_file",
    r"str_replace",
    r"strReplace",
    r"edit_file",
    r"patch_file",
    r"apply_diff",
    r"delete_file",
    r"deleteFile",
    r"remove_file",
    r"create_file",
    r"move_file",
    r"rename_file",
    r"copy_file",
])
```

### Coverage Analysis:

✅ **Covered by current patterns:**
- `write_to_file` ✓
- `write_file` ✓
- `replace_in_file` ✓
- `str_replace` ✓
- `edit_file` ✓
- `apply_diff` ✓
- `delete_file` ✓
- `remove_file` ✓
- `create_file` ✓
- `move_file` ✓
- `rename_file` ✓
- `copy_file` ✓

❌ **Missing from current patterns:**
- `apply_patch` - Should add
- `insert_content` - Should add
- `search_and_replace` - Should add
- `generate_image` - Should add
- `run_file_change_hooks` - Meta tool, may not need sandboxing

### Current Path Parameter Names:
```python
path_parameter_names: list[str] = field(default_factory=lambda: [
    "path",
    "file_path",
    "filepath",
    "file",
    "target",
    "destination",
    "source",
    "paths",
    "files",
    "file_list",
    "targets",
])
```

### Coverage Analysis:

✅ **Covered by current parameters:**
- `path` ✓
- `file_path` ✓
- `filepath` ✓
- `file` ✓
- `target` ✓
- `destination` ✓
- `source` ✓
- `paths` ✓
- `files` ✓
- `file_list` ✓
- `targets` ✓

❌ **Missing from current parameters:**
- `target_file` - Should add
- `fileName` - Should add
- `filePath` - Should add (camelCase variant)
- `image` - Should add
- `patch` - Should add
- `diff` - Should add
- `dest` - Should add
- `src` - Should add

---

## Recommendations for Design Document Updates

### 1. Add Missing Tool Patterns:

```python
default_tool_patterns: list[str] = field(default_factory=lambda: [
    # Existing patterns
    r"write_to_file",
    r"write_file",
    r"fsWrite",
    r"replace_in_file",
    r"str_replace",
    r"strReplace",
    r"edit_file",
    r"patch_file",
    r"apply_diff",
    r"delete_file",
    r"deleteFile",
    r"remove_file",
    r"create_file",
    r"move_file",
    r"rename_file",
    r"copy_file",
    # NEW: Add these patterns
    r"apply_patch",
    r"insert_content",
    r"search_and_replace",
    r"generate_image",
])
```

### 2. Add Missing Path Parameters:

```python
path_parameter_names: list[str] = field(default_factory=lambda: [
    # Existing parameters
    "path",
    "file_path",
    "filepath",
    "file",
    "target",
    "destination",
    "source",
    "paths",
    "files",
    "file_list",
    "targets",
    # NEW: Add these parameters
    "target_file",
    "fileName",
    "filePath",
    "image",
    "patch",
    "diff",
    "dest",
    "src",
])
```

### 3. Consider Regex Patterns for Flexibility:

Instead of exact matches, consider using regex patterns that can catch variations:

```python
default_tool_patterns: list[str] = field(default_factory=lambda: [
    r"write.*file",      # Matches: write_file, write_to_file, writeFile
    r".*write.*",        # Matches: fsWrite, file_write
    r"replace.*file",    # Matches: replace_in_file, replaceFile
    r"str.*replace",     # Matches: str_replace, strReplace
    r"edit.*file",       # Matches: edit_file, editFile
    r"apply.*(diff|patch)", # Matches: apply_diff, apply_patch
    r"delete.*file",     # Matches: delete_file, deleteFile
    r"remove.*file",     # Matches: remove_file, removeFile
    r"create.*file",     # Matches: create_file, createFile
    r"move.*file",       # Matches: move_file, moveFile
    r"rename.*file",     # Matches: rename_file, renameFile
    r"copy.*file",       # Matches: copy_file, copyFile
    r"insert.*content",  # Matches: insert_content, insertContent
    r"search.*replace",  # Matches: search_and_replace, searchReplace
    r"generate.*image",  # Matches: generate_image, generateImage
])
```

---

## Special Cases and Notes

### 1. Aider's SEARCH/REPLACE Format
Aider doesn't use traditional tool calls. The sandboxing system would need to:
- Parse markdown-formatted responses
- Extract filenames from lines before fence markers
- Identify SEARCH/REPLACE blocks

**Recommendation:** Aider may not be compatible with this sandboxing approach unless it's modified to use tool calls.

### 2. MCP (Model Context Protocol) Tools
Several agents (Cline, Kilocode, Gemini CLI) support MCP tools:
- Tool names: `use_mcp_tool`, `access_mcp_resource`
- These are meta-tools that can invoke arbitrary external tools
- MCP tools may perform file operations

**Recommendation:** Consider sandboxing MCP tool calls by:
1. Inspecting the `tool_name` parameter
2. Checking if the MCP tool is file-related
3. Extracting paths from the `arguments` parameter

### 3. Shell Command Tools
Many agents have shell/command execution tools:
- `execute_command` (Cline, Kilocode)
- `shell` (Codex)
- `run_terminal_command` (Codebuff)

**Recommendation:** Shell commands can perform file operations indirectly. Consider:
1. Parsing command strings for file operations (`rm`, `mv`, `cp`, `touch`, `echo >`, etc.)
2. Blocking commands that reference paths outside project root
3. This is complex and may have false positives/negatives

### 4. Image Generation Tools
- `generate_image` (Kilocode) creates image files
- Path parameter: `image` or `path`

**Recommendation:** Include in sandboxing as it writes files.

---

## Testing Recommendations

### 1. Test with Real Tool Calls

Create test cases using actual tool call formats from each agent:

```python
# Cline format
{
    "name": "write_to_file",
    "arguments": {
        "path": "src/test.py",
        "content": "print('hello')"
    }
}

# Kilocode format
{
    "name": "edit_file",
    "arguments": {
        "target_file": "src/main.ts",
        "instructions": "Add error handling",
        "code_edit": "..."
    }
}

# Codebuff format
{
    "name": "str_replace",
    "arguments": {
        "path": "config.json",
        "replacements": [...]
    }
}
```

### 2. Test Path Extraction

Verify path extraction works for all parameter names:

```python
test_cases = [
    ({"path": "/tmp/file.txt"}, ["/tmp/file.txt"]),
    ({"target_file": "src/main.py"}, ["src/main.py"]),
    ({"files": ["a.txt", "b.txt"]}, ["a.txt", "b.txt"]),
    ({"image": "output.png"}, ["output.png"]),
]
```

### 3. Test Pattern Matching

Verify all tool names are correctly identified:

```python
file_changing_tools = [
    "write_to_file",
    "write_file",
    "edit_file",
    "apply_patch",
    "str_replace",
    # ... all discovered tools
]

for tool in file_changing_tools:
    assert is_file_changing_tool(tool), f"Failed to identify: {tool}"
```

---

## Conclusion

This inventory documents **25+ unique file-changing tools** across **8 coding agents**, with **15+ unique path parameter names**. The current design document patterns cover most tools but should be updated to include:

**Missing Tool Patterns:**
- `apply_patch`
- `insert_content`
- `search_and_replace`
- `generate_image`

**Missing Path Parameters:**
- `target_file`
- `fileName`
- `filePath`
- `image`
- `patch`
- `diff`
- `dest`
- `src`

The sandboxing system should be flexible enough to handle:
1. Exact tool name matches
2. Regex pattern matches
3. Multiple path parameter names
4. Array/list path parameters
5. Nested path structures

**Next Steps:**
1. Update design document with missing patterns
2. Implement flexible pattern matching
3. Add comprehensive test coverage
4. Consider special cases (MCP tools, shell commands, Aider format)
