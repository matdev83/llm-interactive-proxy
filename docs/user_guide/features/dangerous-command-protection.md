# Dangerous Command Protection

The proxy includes built-in protection against dangerous git commands that could potentially destroy your work or repository history.

## Overview

This safety feature detects and blocks destructive git operations before they can cause damage. It uses pattern-based detection to identify dangerous commands at the tool call level and intercepts them in real-time.

**Note**: Developer tools like linters, formatters, and type checkers (ruff, black, mypy, eslint, etc.) are automatically exempted from dangerous command detection. See [Developer Tool Exemptions](./dangerous-command-protection-dev-tools.md) for details.

## Key Features

- **Pattern-Based Detection**: Uses regex patterns to identify dangerous git commands
- **Real-Time Blocking**: Intercepts dangerous commands at the tool call level
- **Comprehensive Coverage**: Blocks 30+ dangerous git operations
- **Descriptive Feedback**: Returns clear messages explaining why commands were blocked
- **Safer Alternatives**: Suggests safer alternatives when appropriate
- **Audit Logging**: Logs all blocked attempts for debugging and security auditing

## Protected Commands

The following types of dangerous git commands are blocked:

- `git reset --hard` (discards all local changes)
- `git clean -f` (deletes untracked files)
- `git push --force` (overwrites remote history)
- `git branch -D` (force deletes branches)
- `git restore .` (discards unstaged changes)
- `git filter-branch --prune-empty` (rewrites history)
- And many more destructive operations

## Configuration

Configuration follows precedence: CLI > Environment > Config File

### CLI Flags

```bash
# Disable protection (overwrites config file and environment variable)
--disable-dangerous-git-commands-protection
```

### Environment Variables

```bash
# Enable or disable protection
export DANGEROUS_COMMAND_PREVENTION_ENABLED=true  # or false
```

### Config File

```yaml
# config.yaml
session:
  dangerous_command_prevention_enabled: true
```

## Usage Examples

### Default: Protection Enabled

```bash
# Protection is enabled by default
python -m src.core.cli --default-backend openai
```

### Explicitly Disable Protection

```bash
# Only disable if you understand the risks
python -m src.core.cli --disable-dangerous-git-commands-protection
```

### Enable via Environment Variable

```bash
export DANGEROUS_COMMAND_PREVENTION_ENABLED=true
python -m src.core.cli
```

### Disable via Environment Variable

```bash
export DANGEROUS_COMMAND_PREVENTION_ENABLED=false
python -m src.core.cli
```

## Behavior

When a dangerous git command is detected, the proxy:

1. Blocks the tool call execution
2. Returns a descriptive steering message explaining why the command was blocked
3. Logs the blocked attempt for debugging and security auditing
4. Suggests safer alternatives when appropriate

### Example Blocked Commands

```bash
# These commands will be blocked:
git reset --hard HEAD
git clean -f
git push --force origin main
git restore .
git branch -D feature-branch
git filter-branch --prune-empty
```

## Use Cases

- **Prevent Accidental Data Loss**: Stop LLM agents from accidentally destroying work
- **Repository Safety**: Protect repository history from destructive operations
- **Team Collaboration**: Prevent force pushes that could affect other team members
- **Development Safety**: Add a safety net during automated development workflows
- **Learning Environments**: Protect students and learners from destructive mistakes

## When to Disable

Only disable this protection if you:

- Understand the risks of the specific commands you need to execute
- Have legitimate reasons to execute these commands
- Have proper backups and recovery procedures in place
- Are working in an isolated or test environment

**Note**: This protection is enabled by default for security. Exercise caution when disabling it.

## Related Features

- [Tool Access Control](tool-access-control.md) - Fine-grained control over tool execution
- [File Access Sandboxing](file-sandboxing.md) - Restrict file operations to project directory
- [Inline Python Steering](inline-python-steering.md) - Prevent unstable inline Python execution
- [Quality Verifier System](quality-verifier.md) - Real-time response verification
