# Agent Development Guidelines

## Never Use Unicode Emojis

- Use ASCII characters instead of emojis
- Avoid using emojis in code comments or docstrings

## Build/Lint/Test Commands

- Install dependencies: `./.venv/Scripts/python.exe -m pip install -e .[dev]`
- Run all tests: `./.venv/Scripts/python.exe -m pytest`
- Run specific test: `./.venv/Scripts/python.exe -m pytest tests/unit/test_file.py::test_name`
- Lint code: `./.venv/Scripts/python.exe -m ruff --fix check .`
- Format code: `./.venv/Scripts/python.exe -m black .`

## Code Style Guidelines

- Follow PEP 8 and use type hints for all functions
- Use ruff for linting (see ruff.toml) and black for formatting
- Import order: standard library, third-party, local imports (separated by blank lines)
- Naming conventions: snake_case for variables/functions, PascalCase for classes
- Error handling: Use specific exceptions and include meaningful error messages
- Prefer f-strings for string formatting

### Error Handling Strategy

The project uses a custom exception hierarchy to provide detailed and consistent error information. All custom exceptions inherit from `LLMProxyError`.

When handling errors, follow these guidelines:

- **Catch specific exceptions** whenever possible. Avoid broad `except Exception` blocks.
- If a broad exception must be caught, **log the error with `exc_info=True`** and re-raise a more specific custom exception.
- Use the most specific exception class available from `src.core.common.exceptions` that accurately describes the error.
- When creating new exceptions, ensure they inherit from the appropriate base class (e.g., `BackendError`, `CommandError`).
- Provide clear, helpful error messages and include relevant details in the `details` dictionary of the exception.

## Development Workflow

1. Write tests first (TDD)
2. Run tests to confirm they fail: `./.venv/Scripts/python.exe -m pytest tests/unit/test_file.py::test_name`
3. Implement minimal code to pass tests
4. Run linter: `./.venv/Scripts/python.exe -m ruff --fix check .`
5. Run all tests: `./.venv/Scripts/python.exe -m pytest`

## Code Quality Standards

- Follow SOLID principles:
  - Single Responsibility Principle (SRP): A class should have only one reason to change
  - Open/Closed Principle (OCP): Software entities should be open for extension, but closed for modification
  - Liskov Substitution Principle (LSP): Objects should be replaceable with instances of their subtypes
  - Interface Segregation Principle (ISP): Clients should not be forced to depend on interfaces they do not use
  - Dependency Inversion Principle (DIP): High-level modules should not depend on low-level modules
- Apply DRY (Don't Repeat Yourself) principle to avoid code duplication
- Maintain modular and layered architecture with clear separation of concerns
- Ensure easy testability of all components
- Write code that is maintainable and follows established patterns

## Project Improvement Guidelines

- Agents should only make changes that improve the codebase:
  - Add new functions/methods
  - Improve existing functions/methods
  - Improve code structure and maintainability
  - Add new functionalities
- Agents are NOT allowed to degrade the project by:
  - Removing functions or functionalities
  - Removing files or features
  - Degrading code quality
- Exceptions: Only remove code/features when EXPLICITLY requested by the user

## Dependency Management

- Agents are NOT allowed to manually install any modules by issuing `pip` commands
- All dependency management MUST be done by modifications to the pyproject.toml file
- After adding new dependency, install dependencies with: `./.venv/Scripts/python.exe -m pip install -e .[dev]`

## Project Structure

- src/: Source code
- tests/: Unit and integration tests
- config/: Configuration files
- docs/: Documentation
- examples/: Usage examples
- var/: Runtime data directory
  - var/logs/: Log files (with PID in filename for concurrent execution safety)
  - var/wire_captures_json/: JSON wire capture files (when enabled via CLI)
  - var/wire_captures_cbor/: CBOR wire capture files (when enabled via CLI, named to match log files)

## Debugging and Wire Captures

### Log Files and Wire Captures Location

- All log files and wire capture files are stored in the `./var` subfolder in the project's root
- Log files include PIDs in filenames for safe concurrent execution (e.g., `proxy-12345.log`)
- CBOR wire capture files are automatically named to match their corresponding log files (e.g., `proxy-12345.cbor`)
- This unified naming makes it easy to correlate log files with their wire captures
- Wire captures are only created when explicitly enabled via CLI parameters

### Reading CBOR Wire Capture Files

CBOR (Concise Binary Object Representation) wire capture files contain binary-encoded request/response data.

**1. Using the CLI Tool (Recommended)**

The project includes a built-in CLI tool to inspect CBOR capture files:

```bash
# Inspect a capture file (shows summary)
./.venv/Scripts/python.exe -m src.core.simulation.cli inspect --capture ./var/wire_captures_cbor/capture_file.cbor

# Inspect with first 5 entries
./.venv/Scripts/python.exe -m src.core.simulation.cli inspect --capture ./var/wire_captures_cbor/capture_file.cbor --entries 5

# Output summary as JSON
./.venv/Scripts/python.exe -m src.core.simulation.cli inspect --capture ./var/wire_captures_cbor/capture_file.cbor --json
```

**2. Using the Inspection Script (Enhanced)**

For detailed analysis including request/response pairing and issue detection, use the dedicated inspection script. This is the **recommended tool for debugging issues** as it provides:

- Request/response pair analysis
- **Automatic issue detection** (slow responses, rate limits, missing responses, model name leaks)
- **Timeline visualization** with timing gap highlighting
- **Request flow tracking** end-to-end
- **Streaming performance analysis**
- **Session grouping and filtering**
- Traffic direction filtering
- Backend filtering for multi-backend scenarios
- JSON export for further processing

**Quick Debugging Workflow:**

```bash
# 1. Get overview and auto-detect ALL issues (START HERE!)
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --detect-issues

# 2. View timeline to spot timing gaps and slow responses
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --timeline --backend gemini-oauth-plan

# 3. Track specific request flow with timing
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --track-request 2 --backend gemini-oauth-plan

# 4. Investigate context around problematic entry
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --around 83 --context 5

# 5. View last entries to see where session stalled
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --last 20 --verbose

# 6. Analyze streaming performance
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --analyze-streaming --backend gemini-oauth-plan
```

**Basic Operations:**

```bash
# List all backends in the capture file
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --list-backends

# Show first 10 entries with data preview
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --entries 10

# Show LAST 10 entries (useful for finding where it stalled)
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --last 10

# Show specific entry range
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --range 80-98

# Jump to specific entry
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --entry 83 --verbose

# Filter entries by backend
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --backend openai --entries 10

# Group entries by session
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --group-by-session

# Analyze request/response pairs (original feature, still useful)
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --analyze --backend anthropic
```

**Combining Features:**

```bash
# Timeline + issue detection for specific backend
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --detect-issues --timeline --backend gemini-oauth-plan

# Search with context window
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --search "git commit" --around 83 --context 5
```

The `--detect-issues` flag will automatically detect and report:
- **Slow responses** (timing gaps >10s between entries)
- **Rate limiting errors** (quota exceeded, throttling)
- **Missing responses** (requests with no backend response - stalled sessions)
- **Backend errors** (error responses from API)
- Empty responses (completion_tokens=0)
- Internal model name leaks (e.g., 'code-assist-model' instead of requested model)
- Fallback mechanism activation

The `--timeline` flag provides visual timeline with:
- Timing gaps highlighted (>10s marked as "SLOW")
- Millisecond/second deltas between entries
- Entry sequence, direction, size, backend, and session ID
- Perfect for spotting performance issues at a glance

**3. Programmatic Access (Python)**

Use the `CaptureReader` class to read capture files in your code:

```python
from src.core.simulation.capture_reader import CaptureReader

reader = CaptureReader()
session = reader.load("./var/wire_captures_cbor/capture_file.cbor")

# Access summary
summary = reader.summarize()

# Access entries
for entry in session.entries:
    print(f"Timestamp: {entry.timestamp}, Direction: {entry.direction}")
    print(f"Data: {entry.data}")
```

## Important Notes

- Development is being made on Windows PC
- Linux based coding agents are using WSL and are expected to still use this Python binary: `./.venv/Scripts/python.exe` even if they believe they should use the linux-one
- Make sure it is clear that all executions of Python based commands use this exact interpreter (exe file) from within the .venv folder
- Always activate virtual environment from .venv before running commands
- Prove code works by running tests before submitting tasks
