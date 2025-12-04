# Building

This guide covers how to set up your development environment, install dependencies, and build the LLM Interactive Proxy.

## Prerequisites

- **Python 3.10 or higher**: The project requires Python 3.10+
- **pip**: Python package installer (usually included with Python)
- **Git**: For cloning the repository
- **Virtual environment**: Recommended for isolation

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/matdev83/llm-interactive-proxy.git
cd llm-interactive-proxy
```

### 2. Create Virtual Environment

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows:
.venv\Scripts\activate

# On Linux/macOS:
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
# Install the package in editable mode with development dependencies
./.venv/Scripts/python.exe -m pip install -e .[dev]
```

This installs:

- The proxy package in editable mode (`-e`)
- All runtime dependencies
- All development dependencies (`[dev]`)

## Dependency Management

### Adding Dependencies

All dependencies are managed through `pyproject.toml`. Never install packages directly with `pip install <package>`.

#### Adding Runtime Dependencies

Edit `pyproject.toml` and add the package to the `dependencies` list:

```toml
[project]
dependencies = [
    "fastapi>=0.104.0",
    "httpx>=0.25.0",
    # Add your new dependency here
    "new-package>=1.0.0",
]
```

#### Adding Development Dependencies

Edit `pyproject.toml` and add the package to the `dev` optional dependencies:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "ruff>=0.1.0",
    # Add your new dev dependency here
    "new-dev-tool>=1.0.0",
]
```

#### Installing After Adding Dependencies

After modifying `pyproject.toml`, reinstall the package:

```bash
./.venv/Scripts/python.exe -m pip install -e .[dev]
```

## Project Structure

```
llm-interactive-proxy/
├── .venv/                  # Virtual environment (created by you)
├── src/                    # Source code
├── tests/                  # Test suite
├── config/                 # Configuration files
├── docs/                   # Documentation
├── scripts/                # Utility scripts
├── var/                    # Runtime data (logs, captures)
├── pyproject.toml          # Project metadata and dependencies
├── setup.py                # Package setup
└── dev/README.md           # Project overview
```

## Build Commands

### Install Package

```bash
# Install in editable mode with dev dependencies
./.venv/Scripts/python.exe -m pip install -e .[dev]

# Install in editable mode without dev dependencies
./.venv/Scripts/python.exe -m pip install -e .

# Install from source (non-editable)
./.venv/Scripts/python.exe -m pip install .
```

### Verify Installation

```bash
# Check installed packages
./.venv/Scripts/python.exe -m pip list

# Verify proxy can be imported
./.venv/Scripts/python.exe -c "import src.core.cli; print('Success!')"
```

## Development Tools

### Code Formatting

```bash
# Format code with black
./.venv/Scripts/python.exe -m black .

# Check formatting without making changes
./.venv/Scripts/python.exe -m black --check .
```

### Linting

```bash
# Run ruff linter
./.venv/Scripts/python.exe -m ruff check .

# Run ruff with auto-fix
./.venv/Scripts/python.exe -m ruff check --fix .
```

### Type Checking

```bash
# Run mypy type checker
./.venv/Scripts/python.exe -m mypy src/
```

## Running the Proxy

### Basic Usage

```bash
# Run with default settings
./.venv/Scripts/python.exe -m src.core.cli

# Run with specific backend
./.venv/Scripts/python.exe -m src.core.cli --default-backend openai

# Run with configuration file
./.venv/Scripts/python.exe -m src.core.cli --config config/config.example.yaml
```

### Common Options

```bash
# Bind to specific host and port
./.venv/Scripts/python.exe -m src.core.cli --host 127.0.0.1 --port 8000

# Disable authentication (local only)
./.venv/Scripts/python.exe -m src.core.cli --disable-auth

# Enable wire capture (See [Wire Capture](../user_guide/debugging/wire-capture.md))
./.venv/Scripts/python.exe -m src.core.cli --capture-file var/wire_captures_json/capture.json

# Enable CBOR wire capture (See [CBOR Capture](../user_guide/debugging/cbor-capture.md))
./.venv/Scripts/python.exe -m src.core.cli --cbor-capture-file var/wire_captures_cbor/capture.cbor
```

## Environment Variables

### Required for Backends

Set environment variables for the backends you plan to use:

```bash
# [OpenAI](../user_guide/backends/openai.md)
export OPENAI_API_KEY="sk-..."

# [Anthropic](../user_guide/backends/anthropic.md)
export ANTHROPIC_API_KEY="sk-ant-..."

# [Gemini](../user_guide/backends/gemini.md)
export GEMINI_API_KEY="AIza..."

# [OpenRouter](../user_guide/backends/openrouter.md)
export OPENROUTER_API_KEY="sk-or-..."

# [ZAI](../user_guide/backends/zai.md)
export ZAI_API_KEY="..."

# Minimax
export MINIMAX_API_KEY="..."

# For Gemini GCP backend
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

### Optional Configuration

```bash
# Enable features
export ENABLE_SANDBOXING=true             # See [File Access Sandboxing](../user_guide/features/file-access-sandboxing.md)
export DANGEROUS_COMMAND_PREVENTION_ENABLED=true  # See [Dangerous Command Protection](../user_guide/features/dangerous-command-protection.md)
export FIX_THINK_TAGS_ENABLED=true        # See [Think Tags Fix](../user_guide/features/think-tags-fix.md)

# [LLM Assessment](../user_guide/features/llm-assessment.md)
export LLM_ASSESSMENT_ENABLED=true
export LLM_ASSESSMENT_BACKEND=openai
export LLM_ASSESSMENT_MODEL=gpt-4o-mini

# [Angel Verification](../user_guide/features/angel-verification.md)
export ANGEL_MODEL="openai:gpt-4o-mini"
export ANGEL_FREQUENCY=1
```

## Platform-Specific Notes

### Windows

- Use `.venv\Scripts\activate` to activate the virtual environment
- Use `./.venv/Scripts/python.exe` for all Python commands
- Use backslashes (`\`) for paths in commands

### Linux/macOS

- Use `source .venv/bin/activate` to activate the virtual environment
- Use `./.venv/bin/python` for all Python commands
- Use forward slashes (`/`) for paths in commands

### WSL (Windows Subsystem for Linux)

When using WSL, still use the Windows Python interpreter:

```bash
# Even in WSL, use the Windows Python executable
./.venv/Scripts/python.exe -m pip install -e .[dev]
```

## Troubleshooting

### Virtual Environment Issues

**Problem**: Virtual environment not activating

**Solution**:

```bash
# Recreate virtual environment
rm -rf .venv
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .[dev]
```

### Dependency Conflicts

**Problem**: Dependency version conflicts

**Solution**:

```bash
# Clear pip cache and reinstall
./.venv/Scripts/python.exe -m pip cache purge
./.venv/Scripts/python.exe -m pip install --force-reinstall -e .[dev]
```

### Import Errors

**Problem**: Cannot import modules from `src`

**Solution**:

```bash
# Ensure package is installed in editable mode
./.venv/Scripts/python.exe -m pip install -e .

# Verify installation
./.venv/Scripts/python.exe -c "import src; print(src.__file__)"
```

### Permission Errors

**Problem**: Permission denied when installing packages

**Solution**:

```bash
# On Windows, run as administrator or use --user flag
./.venv/Scripts/python.exe -m pip install --user -e .[dev]

# On Linux/macOS, check virtual environment ownership
sudo chown -R $USER .venv
```

## Build Artifacts

### Generated Files

The build process generates several artifacts:

- `.venv/`: Virtual environment directory
- `src/llm_interactive_proxy.egg-info/`: Package metadata
- `__pycache__/`: Python bytecode cache
- `.mypy_cache/`: Mypy type checking cache
- `.ruff_cache/`: Ruff linting cache
- `.pytest_cache/`: Pytest cache

### Cleaning Build Artifacts

```bash
# Remove Python cache files
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

# Remove build artifacts
rm -rf src/llm_interactive_proxy.egg-info
rm -rf .mypy_cache .ruff_cache .pytest_cache

# Remove virtual environment (if needed)
rm -rf .venv
```

## Continuous Integration

The project uses GitHub Actions for CI/CD:

- **CI Workflow**: Runs tests, linting, and type checking on every push
- **Architecture Check**: Validates architectural constraints
- **Coverage**: Tracks code coverage with Codecov

See `.github/workflows/` for workflow definitions.

## Related Documentation

- **Testing**: See [testing.md](testing.md) for running tests
- **Contributing**: See [contributing.md](contributing.md) for contribution workflow
- **Code Organization**: See [code-organization.md](code-organization.md) for project structure
- **Coding Standards**: See [AGENTS.md](../../dev/AGENTS.md) for coding standards
