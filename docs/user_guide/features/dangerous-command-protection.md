# Dangerous Command Protection

The proxy includes built-in protection against **destructive shell commands** (especially around **git** and the filesystem) and against several **high-risk shell idioms** (remote download piped into a shell or interpreter, broad process termination, and similar patterns). The goal is to stop agents from running commands that could destroy work, leak data, or take down processes.

## Overview

This safety feature detects and blocks dangerous operations **before** they are forwarded to tooling that runs shell commands. Detection is **pattern-based** on the command string, with a **normalization pass** applied first so common obfuscations are less effective:

- **ANSI terminal escapes** (CSI / OSC sequences) are stripped so color codes cannot hide tokens.
- **NUL bytes** are removed.
- **Unicode NFKC** normalization reduces fullwidth / compatibility-form homoglyphs that could otherwise dodge simple matchers.

After normalization, the proxy matches against a **combined set of rules** (fast path) and detailed per-rule metadata for logging and steering messages.

**Note**: Developer tools like linters, formatters, and type checkers (ruff, black, mypy, eslint, etc.) are automatically exempted from dangerous command detection. See [Developer Tool Exemptions](./dangerous-command-protection-dev-tools.md) for details.

## Key Features

- **Pattern-Based Detection**: Uses regex patterns for destructive git/filesystem commands and selected remote-execution / process-control patterns
- **Normalization Before Matching**: Strips ANSI escapes, NULs, and applies Unicode NFKC to harden against trivial obfuscation
- **Real-Time Blocking**: Intercepts dangerous commands at the tool call level
- **Comprehensive Coverage**: Blocks many destructive git operations plus additional shell-risk patterns (examples below)
- **Descriptive Feedback**: Returns clear messages explaining why commands were blocked
- **Safer Alternatives**: Suggests safer alternatives when appropriate
- **Audit Logging**: Logs all blocked attempts for debugging and security auditing

## Protected commands (examples)

**Git and repository safety** (non-exhaustive):

- `git reset --hard` (discards all local changes)
- `git clean -f` (deletes untracked files)
- `git push --force` (overwrites remote history)
- `git branch -D` (force deletes branches)
- `git restore .` (discards unstaged changes)
- `git filter-branch` / history-rewriting flows
- And many more destructive operations enforced via the shared pattern set

**Additional shell-risk patterns** (illustrative; the exact set evolves with releases):

- Interpreter **heredocs** (`python` / `perl` / `ruby` / `node` with `<<`) often used to smuggle multi-line payloads
- **`curl` / `wget` piped into `bash` / `sh`** or into an interpreter (`python`, `ruby`, …), including some `curl … -O - | …` forms
- **`chmod` make-executable then `./` run** chains
- **`kill` with `$(pgrep …)`**, **`kill -9 -1`**, aggressive **`pkill -9`**
- Classic **fork-bomb** form
- **Redirects** toward sensitive locations such as **`/etc/`** or **`/dev/sd`**-style device paths

The same rules apply whether you use the legacy dangerous-command handler or the **unified tool security** path; both consume the shared configuration and normalization pipeline.

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

- [Outbound URL safety](outbound-url-safety.md) - SSRF-style validation for SSO and catalog HTTP fetches
- [Tool Access Control](tool-access-control.md) - Fine-grained control over tool execution
- [File Access Sandboxing](file-sandboxing.md) - Restrict file operations to project directory
- [Inline Python Steering](inline-python-steering.md) - Prevent unstable inline Python execution
- [Quality Verifier System](quality-verifier.md) - Real-time response verification
