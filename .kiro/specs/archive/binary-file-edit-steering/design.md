# Design Document

---
**Purpose**: Add a steering policy that detects and warns when LLM agents attempt to edit binary files, preventing file corruption from text-based edits.
**Project Context**: Universal LLM Proxy - FastAPI async service with staged initialization, DI containers, adapter pattern for LLM backends.
---

## Overview

The Binary File Edit Steering Policy detects tool calls that attempt to edit files with binary extensions (executables, media, databases, etc.) and returns a steering message warning the agent not to proceed. This prevents file corruption that would result from text-based edits to binary content.

### Goals
- Detect file editing tool calls targeting binary files by extension
- Provide comprehensive coverage of common binary file extensions
- Follow established steering policy patterns (ISteeringPolicy interface)
- Support configuration via CLI > ENV > YAML precedence
- Enable by default with option to disable

### Non-Goals
- Content-based binary detection (magic bytes) - extension-based is sufficient and faster
- Blocking the operation entirely - steering provides guidance, not hard blocks
- Supporting custom extension lists via configuration (future enhancement)

## Architecture

### Existing Architecture Analysis
- Unified steering framework provides `ISteeringPolicy` interface and `UnifiedSteeringHandler`
- Policies are registered in `SteeringStage` and injected into the handler
- Configuration follows CLI > ENV > YAML precedence via applicators
- `FileEditingTools` in `tool_constants.py` defines file editing tool names

### Architecture Pattern & Boundary Map
- Pattern: Policy implementation within existing Unified Steering Framework
- Domain boundaries: Steering remains a middleware/handler concern
- Existing patterns preserved: async-first, DI-based service registration, staged init
- New component: `BinaryFileEditPolicy` implementing `ISteeringPolicy`

### Technology Stack

| Layer | Choice / Version | Role in Feature | Notes |
|-------|------------------|-----------------|-------|
| Runtime | Python 3.10+ / FastAPI (async) | Policy execution | Use `async/await` |
| DI Container | `src/core/di/container.py` | Resolve policy | Registered as singleton |
| Initialization | `SteeringStage` | Register policy | Added to existing stage |
| Config | `src/core/config/app_config.py` | Enable/disable toggle | CLI > ENV > YAML |

## System Flows

```
Tool Call Arrives
       │
       ▼
UnifiedSteeringHandler
       │
       ▼
BinaryFileEditPolicy.evaluate()
       │
       ├─► Is tool a file editing tool? ─► No ─► Return None
       │
       ├─► Is policy enabled? ─► No ─► Return None
       │
       ├─► Extract file path from arguments
       │         │
       │         └─► Path not found ─► Return None
       │
       ├─► Extract extension from path
       │         │
       │         └─► No extension ─► Return None
       │
       └─► Is extension in binary set? ─► No ─► Return None
                  │
                  ▼
           Return SteeringResult with warning message
```

## Requirements Traceability

| Requirement | Summary | Components | Interfaces | Flows |
|-------------|---------|------------|------------|-------|
| 1 | Binary file detection | BinaryFileEditPolicy | ISteeringPolicy | Evaluate flow |
| 2 | Extension coverage | BINARY_EXTENSIONS set | N/A | Extension matching |
| 3 | Configuration | CLI flag, ENV var, config | AppConfig, Applicator | Config resolution |
| 4 | Framework integration | SteeringStage registration | ISteeringPolicy | DI registration |
| 5 | Testing | Unit tests, property tests | N/A | Test execution |

## Components and Interfaces

### BinaryFileEditPolicy (`src/services/steering/policies/binary_file_edit_policy.py`)

| Field | Detail |
|-------|--------|
| Intent | Detect and warn about binary file edit attempts |
| Requirements | 1, 2, 4 |
| Interface | `ISteeringPolicy` |
| DI Lifetime | Singleton |

**Responsibilities & Constraints**
- Check if tool is a file editing tool
- Extract file path from tool arguments
- Check if file extension is in binary set
- Return steering result if binary, None otherwise
- Support prompt override from markdown file

**Dependencies (via DI)**
- None (self-contained policy)

**Key Methods**
```python
class BinaryFileEditPolicy(ISteeringPolicy):
    @property
    def name(self) -> str: return "binary_file_edit"
    
    @property
    def priority(self) -> int: return 90  # High priority
    
    async def evaluate(
        self, context: ToolCallContext, command: str, dry_run: bool = False
    ) -> SteeringResult | None:
        """Evaluate if tool call targets a binary file."""
```

### Binary Extensions Set

Comprehensive set of binary file extensions organized by category:

```python
BINARY_EXTENSIONS: frozenset[str] = frozenset({
    # Executables & Libraries
    ".exe", ".dll", ".so", ".dylib", ".bin", ".elf", ".com", ".msi",
    ".app", ".deb", ".rpm", ".dmg", ".iso", ".img", ".apk", ".ipa",
    
    # Compiled/Object Files
    ".o", ".obj", ".a", ".lib", ".pyc", ".pyo", ".pyd", ".class",
    ".jar", ".war", ".ear", ".whl", ".egg",
    
    # Databases
    ".db", ".sqlite", ".sqlite3", ".mdb", ".accdb", ".dbf", ".frm",
    ".ibd", ".myd", ".myi", ".ldf", ".mdf", ".ndf",
    
    # Media - Audio
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus",
    ".aiff", ".ape", ".mid", ".midi",
    
    # Media - Video
    ".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".3gp", ".mpeg", ".mpg", ".vob", ".ogv",
    
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".ico",
    ".webp", ".psd", ".ai", ".eps", ".raw", ".cr2", ".nef", ".heic",
    ".heif", ".dng", ".arw", ".orf",
    
    # Documents (Binary formats)
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf",
    ".odt", ".ods", ".odp", ".rtf",
    
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".cab",
    ".arj", ".lzh", ".lzma", ".z", ".tgz", ".tbz2",
    
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".fon",
    
    # 3D/CAD/Game Assets
    ".blend", ".fbx", ".3ds", ".max", ".dwg", ".dxf", ".obj",
    ".stl", ".gltf", ".glb", ".unity3d", ".asset", ".pak", ".bundle",
    
    # Other Binary
    ".dat", ".swf", ".fla", ".pdb", ".dmp", ".core",
})
```

### File Path Extraction

Extract file path from tool arguments using common parameter names:

```python
PATH_PARAMETER_NAMES: tuple[str, ...] = (
    "path", "file_path", "target_file", "filename", "file",
    "destination", "dest", "target", "filepath", "file_name",
    "new_path", "old_path", "source", "src",
)
```

### Configuration

**AppConfig Addition** (`src/core/config/app_config.py`):
```python
binary_file_edit_steering_enabled: bool = True
"""Whether binary file edit steering is enabled (default: True)."""

binary_file_edit_steering_message: str | None = None
"""Optional custom steering message for binary file edit attempts."""
```

**CLI Flag** (`src/core/cli_support/argument_parser_builder.py`):
```python
parser.add_argument(
    "--disable-binary-file-edit-steering",
    action="store_true",
    dest="disable_binary_file_edit_steering",
    default=None,
    help="Disable binary file edit steering (overrides config)",
)
```

**Environment Variable**: `DISABLE_BINARY_FILE_EDIT_STEERING`

**Applicator** (`src/core/cli_support/applicators/session_applicator.py`):
```python
if getattr(args, "disable_binary_file_edit_steering", None) is True:
    session = overrides.setdefault("session", {})
    tool_call_reactor = session.setdefault("tool_call_reactor", {})
    tool_call_reactor["binary_file_edit_steering_enabled"] = False
```

## Data Models

Uses existing `SteeringResult` model:
```python
SteeringResult(
    message="...",
    should_block=True,
    policy_name="binary_file_edit",
    severity="warning",
    metadata={
        "tool_name": "...",
        "file_path": "...",
        "extension": "...",
        "source": "binary_file_edit_steering",
    },
)
```

## Error Handling

- If file path extraction fails: log at DEBUG level, return None
- If extension extraction fails: return None (no extension = not binary)
- Policy errors caught by UnifiedSteeringHandler; logged with `exc_info=True`
- Use existing steering/LLMProxyError hierarchy

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Based on the prework analysis, the following properties should be verified:

### Property 1: Binary extensions trigger steering
*For any* file editing tool call with a file path ending in a binary extension, the policy SHALL return a non-None SteeringResult.
**Validates: Requirements 1.1**

### Property 2: Non-binary extensions pass through
*For any* file editing tool call with a file path ending in a non-binary extension (e.g., .py, .js, .txt, .md), the policy SHALL return None.
**Validates: Requirements 1.2**

### Property 3: Disabled policy returns None
*For any* tool call when the policy is disabled, the policy SHALL return None regardless of the file extension.
**Validates: Requirements 1.3**

### Property 4: Path extraction from various parameter names
*For any* tool arguments containing a file path under any of the supported parameter names (path, file_path, target_file, etc.), the policy SHALL correctly extract the path.
**Validates: Requirements 1.5**

### Property 5: Case-insensitive extension matching
*For any* binary extension in any case variation (e.g., .EXE, .Exe, .exe), the policy SHALL recognize it as binary.
**Validates: Requirements 2.10**

## Testing Strategy

**Property-Based Testing Library**: Hypothesis (Python)

**Dual Testing Approach**:
- Unit tests verify specific examples and edge cases
- Property tests verify universal properties across all inputs

### Unit Tests
- Test each category of binary extensions is recognized (2.1-2.9)
- Test file editing tool recognition (1.4)
- Test CLI flag disables policy (3.1)
- Test ENV var disables policy (3.2)
- Test config file disables policy (3.3)
- Test configuration precedence (3.4)
- Test default enabled state (3.5)
- Test prompt override loading (4.3)
- Test telemetry emission (4.4)
- Test priority configuration (4.5)

### Property-Based Tests
Each property test should run minimum 100 iterations.

```python
# Property 1: Binary extensions trigger steering
@given(st.sampled_from(list(BINARY_EXTENSIONS)))
@settings(max_examples=100)
def test_binary_extensions_trigger_steering(extension):
    """**Feature: binary-file-edit-steering, Property 1: Binary extensions trigger steering**"""
    # Generate random filename with binary extension
    # Verify policy returns SteeringResult

# Property 2: Non-binary extensions pass through  
@given(st.sampled_from([".py", ".js", ".ts", ".txt", ".md", ".json", ".yaml"]))
@settings(max_examples=100)
def test_non_binary_extensions_pass_through(extension):
    """**Feature: binary-file-edit-steering, Property 2: Non-binary extensions pass through**"""
    # Generate random filename with non-binary extension
    # Verify policy returns None

# Property 3: Disabled policy returns None
@given(st.sampled_from(list(BINARY_EXTENSIONS) + [".py", ".js"]))
@settings(max_examples=100)
def test_disabled_policy_returns_none(extension):
    """**Feature: binary-file-edit-steering, Property 3: Disabled policy returns None**"""
    # Create disabled policy
    # Verify returns None for any extension

# Property 4: Path extraction from various parameter names
@given(st.sampled_from(PATH_PARAMETER_NAMES), st.text(min_size=1, max_size=50))
@settings(max_examples=100)
def test_path_extraction_from_parameter_names(param_name, filename):
    """**Feature: binary-file-edit-steering, Property 4: Path extraction from various parameter names**"""
    # Create arguments with path under param_name
    # Verify path is extracted correctly

# Property 5: Case-insensitive extension matching
@given(st.sampled_from(list(BINARY_EXTENSIONS)))
@settings(max_examples=100)
def test_case_insensitive_extension_matching(extension):
    """**Feature: binary-file-edit-steering, Property 5: Case-insensitive extension matching**"""
    # Generate random case variations
    # Verify all are recognized as binary
```

### Test Commands
- Fast subset: `./.venv/Scripts/python.exe -m pytest tests/unit/services/steering/test_binary_file_edit_policy.py -v`
- Property tests: `./.venv/Scripts/python.exe -m pytest tests/property/test_binary_file_edit_properties.py -v`
- Full: `./.venv/Scripts/python.exe -m pytest -m "integration or unit"`

## Stage Registration

In `SteeringStage._register_steering_policies()`:
```python
from src.services.steering.policies import BinaryFileEditPolicy

services.add_singleton(
    BinaryFileEditPolicy,
    implementation_factory=lambda provider: BinaryFileEditPolicy(
        message=getattr(reactor_config, "binary_file_edit_steering_message", None),
        enabled=getattr(reactor_config, "binary_file_edit_steering_enabled", True),
        prompt_override_path=Path("config/prompts/steering_binary_file_edit.md"),
    ),
)
```

In `SteeringStage._register_unified_steering_handler()`:
```python
policies = [
    provider.get_required_service(InlinePythonPolicy),
    provider.get_required_service(PytestFullSuitePolicy),
    provider.get_required_service(BinaryFileEditPolicy),  # Add here
    provider.get_required_service(ConfiguredRulesPolicy),
]
```
