# Developer Tool Exemptions in Dangerous Command Protection

## Overview

The dangerous command protection system now includes intelligent exemptions for safe developer tools. This prevents false positives when running linters, formatters, type checkers, and other QA tools that may modify files but are not destructive in a dangerous way.

## Supported Developer Tools

The following developer tools are automatically exempted from dangerous command detection:

### Python Tools
- **ruff** - Python linter and formatter
- **black** - Python code formatter
- **isort** - Python import sorter
- **autopep8** - Python code formatter
- **yapf** - Python formatter
- **mypy** - Static type checker
- **pylint** - Code analysis tool
- **flake8** - Style guide enforcement
- **bandit** - Security linter
- **pyright** - Static type checker
- **pycodestyle** - Style checker
- **pydocstyle** - Docstring checker
- **pytest** - Testing framework

### JavaScript/TypeScript Tools
- **eslint** - Linter
- **prettier** - Code formatter
- **tslint** - TypeScript linter
- **stylelint** - CSS linter
- **jest** - Testing framework
- **mocha** - Testing framework
- **vitest** - Testing framework

### Rust Tools
- **cargo** - Package manager (fmt, clippy, test)
- **rustfmt** - Code formatter
- **clippy** - Linter

### Go Tools
- **gofmt** - Code formatter
- **goimports** - Import formatter
- **golint** - Linter
- **go** - Go toolchain (fmt, test)

### C/C++ Tools
- **clang-format** - Code formatter
- **clang-tidy** - Linter

### General Tools
- **prettier** - Multi-language formatter
- **editorconfig** - Editor configuration

## How It Works

The system uses two detection methods:

1. **Pattern Matching**: Fast regex-based detection of common tool invocations
2. **Fallback Checks**: Secondary checks for tools invoked via language runtimes

## Usage Examples

Safe tool invocations that no longer trigger dangerous command warnings include:

```bash
# Python tools
ruff check --fix .
python -m black src/
./.venv/Scripts/python.exe -m mypy --strict .

# JavaScript tools
eslint --fix src/
npx prettier --write .

# Rust tools
cargo fmt
cargo clippy --fix

# Go tools
gofmt -w .
go fmt ./...
```

## Why This Matters

### Before (False Positive Risk)

Without dev tool exemptions, commands like `ruff --fix` might trigger dangerous command patterns because:
- They modify files automatically
- They use flags that suggest destructive operations
- Pattern matching could confuse them with actual dangerous commands

### After (Smart Detection)

With dev tool exemptions:
- QA tools are recognized and allowed
- Actual dangerous commands (like `rm -rf`) are still blocked
- Developers can use their normal workflows without interruption

## Use Cases

- Developers running code formatters and linters locally without false alarms.
- Continuous integration pipelines that invoke static analysis tools.
- Automated build steps that run test suites and code quality checks before deployment.

## Configuration

Developer tool exemptions are enabled by default and require no configuration. The system automatically:
- Detects dev tool invocations
- Allows them to proceed
- Logs them at DEBUG level (not WARNING)

## Technical Details

### Implementation

The exemption logic is implemented in `CommandExtractionService.is_safe_dev_tool_command()`:

1. Quick pattern match for performance
2. Tool name extraction from various invocation styles
3. Support for wrapped invocations (python -m tool, npx tool, etc.)

### Security Considerations

Developer tools are considered safe because:
- They operate on code/configuration files within the project
- They follow established coding standards
- They are essential for development workflows
- They don't delete entire directories or rewrite git history

Actual dangerous operations like:
- `rm -rf /`
- `git reset --hard`
- `git push --force`
- Windows recursive deletion commands

...are still properly detected and blocked.

## Extending the Whitelist

If you need to add additional safe tools, you can:

1. Submit a PR to add the tool to `CommandExtractionService._SAFE_DEV_TOOLS`
2. Or open an issue describing the tool and why it should be exempted

## Related Documentation

- [Dangerous Command Protection](./dangerous-command-protection.md)
- [Command Extraction Service](../../development_guide/architecture/command-extraction.md)

