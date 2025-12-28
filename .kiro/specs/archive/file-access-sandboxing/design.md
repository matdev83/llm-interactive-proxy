# File Access Sandboxing - Design

## Overview

Add sandboxing to block file operations outside the project directory. Integrates with the existing tool call reactor system to intercept and validate file paths.

## Architecture

Flow: LLM Response → Tool Call Reactor → Sandboxing Handler → Path Validation → Block or Allow

Components:
- **Config**: Add `sandboxing` section to `AppConfig`
- **Handler**: `FileSandboxingHandler` registered with tool call reactor
- **Validator**: `PathValidationService` for path normalization and boundary checks
- **Session**: Use existing `SessionState.project_dir`

## Components

### 1. Configuration

```python
@dataclass(frozen=True)
class SandboxingConfiguration:
    enabled: bool = False
    tool_patterns: list[str] = field(default_factory=lambda: [
        r"write_file", r"fsWrite", r"str_replace", r"strReplace",
        r"edit_file", r"delete_file", r"deleteFile", r"create_file",
        r"move_file", r"rename_file", r"copy_file"
    ])
    path_params: list[str] = field(default_factory=lambda: [
        "path", "file_path", "filepath", "file", "target", 
        "destination", "source", "paths", "files"
    ])
```

CLI: `--enable-sandboxing`
Env: `ENABLE_SANDBOXING=true`
YAML: `sandboxing.enabled: true`

### 2. Path Validator

```python
class PathValidationService:
    def normalize_path(self, path: str, base_dir: str | None = None) -> Path:
        """Normalize to absolute path, expand ~, resolve .., symlinks."""
        if path.startswith("~"):
            path = os.path.expanduser(path)
        path_obj = Path(path)
        if not path_obj.is_absolute():
            path_obj = Path(base_dir or Path.cwd()) / path_obj
        return path_obj.resolve()
    
    def is_within_boundary(self, path: Path, boundary: Path) -> bool:
        """Check if path is within boundary using relative_to()."""
        try:
            path.relative_to(boundary)
            return True
        except ValueError:
            return False
    
    def extract_paths(self, arguments: dict, param_names: list[str]) -> list[str]:
        """Extract paths from tool arguments (handles strings and lists)."""
        paths = []
        for name in param_names:
            val = arguments.get(name)
            if isinstance(val, str):
                paths.append(val)
            elif isinstance(val, list):
                paths.extend(v for v in val if isinstance(v, str))
        return paths
```

### 3. Sandboxing Handler

```python
class FileSandboxingHandler:
    def __init__(self, config, path_validator, session_service):
        self._config = config
        self._validator = path_validator
        self._sessions = session_service
        self._patterns = [re.compile(p, re.I) for p in config.tool_patterns]
    
    def _is_file_tool(self, tool_name: str) -> bool:
        return any(p.search(tool_name) for p in self._patterns)
    
    async def handle(self, context: ToolCallContext) -> ToolCallContext:
        if not self._config.enabled or not self._is_file_tool(context.tool_name):
            return context
        
        session = await self._sessions.get_session(context.session_id)
        if not session.state.project_dir:
            return context  # No project root, allow
        
        project_root = Path(session.state.project_dir)
        paths = self._validator.extract_paths(context.arguments, self._config.path_params)
        
        for path_str in paths:
            try:
                normalized = self._validator.normalize_path(path_str, str(project_root))
                if not self._validator.is_within_boundary(normalized, project_root):
                    context.blocked = True
                    context.block_reason = f"File operation outside project root. Allowed: {project_root}"
                    logger.warning(f"Blocked {context.tool_name} accessing {path_str}")
                    break
            except ValueError as e:
                logger.error(f"Path validation failed: {e}")
                context.blocked = True
                context.block_reason = "Invalid file path"
                break
        
        return context
```

### 4. Registration

Register handler in `application_builder.py`:

```python
def _register_sandboxing_handler(app_config, reactor, validator, sessions):
    if not app_config.sandboxing.enabled:
        return
    handler = FileSandboxingHandler(app_config.sandboxing, validator, sessions)
    reactor.register_handler("file_sandboxing", handler.handle, priority=80)
```

## Testing

- Unit tests: Path normalization, boundary checks, tool matching
- Integration tests: End-to-end with real tool calls, cross-platform paths
- Test fixtures: Valid/invalid paths, relative paths, symlinks, edge cases
