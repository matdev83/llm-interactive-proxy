# Rules for coding agents

Language: **English**.

<!-- KIRO-SPEC:START -->
## Kiro Spec-Driven Development

### When to Use Kiro Specs

**Suggest spec workflow** when request involves: new features, breaking changes, architecture shifts, complex integrations, or unclear requirements needing structured analysis.

**Code directly** for: quick fixes, simple bugs, trivial changes, or when user explicitly says "just code this".

### Opt-In Scope (Important)

Kiro specs are **user-driven and opt-in**.

- **Only enforce spec gating** (e.g., "no code edits until requirements/design are approved") when the user:
  - invokes a `/kiro:*` command, or
  - explicitly references a spec by name/path (e.g., `request-processor-refactoring`, `.kiro/specs/<feature>/`), or
  - explicitly says to use Kiro/spec workflow.
- If the user does **not** mention Kiro or a spec name/path, proceed with normal engineering work. You may still suggest a spec workflow for complex requests, but do not block implementation by default.

### Kiro Commands (User-Triggered)

When working on specs, the user will invoke `/kiro:*` commands. Follow the instructions provided in each command's context.

**Workflow order**: `spec-init` → `spec-requirements` → `spec-design` → `spec-tasks` → `spec-impl`

**Spec-driven rule**: When a spec exists at `.kiro/specs/{feature}/` and you are sure current session is about this spec (see "Opt-In Scope" above): no code edits until `requirements.md` and `design.md` are approved (check `spec.json` for approval status). Every task in `tasks.md` must reference at least one acceptance criterion from requirements.

**Key locations**:

- Specs: `.kiro/specs/{feature-name}/` (requirements.md, design.md, tasks.md, research.md)
- Steering (project memory): `.kiro/steering/` - load when generating specs
- Kiro workflow guide: `.kiro/AGENTS.md` (detailed phase-by-phase reference)
- Templates: `.kiro/settings/templates/`
- Rules: `.kiro/settings/rules/`

<!-- KIRO-SPEC:END -->

## Project Identity

**Universal LLM Proxy** built with **FastAPI (Async)** using **Staged Initialization**.

- **Core Features**: Traffic routing, failover, accounting, and byte-precise **CBOR wire captures**.
- **Architecture**: Service-based (DI), Staged startup (`src/core/app/stages`), Adapter pattern for LLM backends.

## Quick Start

1. **Environment**: Windows-based. ALWAYS use `./.venv/Scripts/python.exe`.
2. **Config**: `cp config/config.example.yaml config/config.yaml` (if missing).
3. **Start**: `./.venv/Scripts/python.exe -m src.core.cli`
4. **Onboarding**: Open `README.md` for fundamental project description.
5. **Docs**: Check `docs/` for architecture deep-dives.
6. **Logs**: Check `var/logs/` for runtime logs.
7. **Captures**: Check `var/wire_captures_cbor/` for binary captures of all traffic. Use `scripts/inspect_cbor_capture.py` to inspect them.

## Key Architecture Paths

| Path | Purpose |
|------|---------|
| `src/core/cli.py` | **Entry Point**. CLI args -> Config -> App Builder. |
| `src/core/app/stages/` | **Startup Logic**. Infrastructure -> Services -> Backends -> Controllers. |
| `src/connectors/` | **Backends**. Implementations for OpenAI, Gemini, Anthropic, etc. |
| `src/core/simulation/` | **Debugging**. Traffic replay & inspection tools (`capture_reader.py`). |
| `var/wire_captures_cbor/` | **Data**. Binary captures of all traffic (pair with `var/logs/`). |

## Script Organization

- **`scripts/`**: Tools for the **end user** ONLY.
- **`dev/`**: All development artifacts, debugging tools, and internal scripts.

## Commands & Workflow

**Rule**: Edit `pyproject.toml` for deps. **NO** manual `pip install`. **NO** emojis.

| Action | Command |
|--------|---------|
| Manage Alembic config | `./.venv/Scripts/python.exe dev/scripts/manage_alembic_config.py <alembic_args>` |
| Test (Default) | `./.venv/Scripts/python.exe -m pytest` (uses `pyproject.toml` addopts) |
| Test (Unit) | `./.venv/Scripts/python.exe -m pytest tests/unit` |
| Test (Integration) | `./.venv/Scripts/python.exe -m pytest tests/integration` |
| **Lint/Fix** | `./.venv/Scripts/python.exe -m ruff check --fix .` |
| **Format** | `./.venv/Scripts/python.exe -m black .` |
| **Boundary Type Check** | `./.venv/Scripts/python.exe dev/scripts/check_boundary_types.py` |
| **Circular import scan (pycycle)** | `./.venv/Scripts/python.exe dev/scripts/run_pycycle.py` |
| **Inspect CBOR wire captures** | `./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py <file> --detect-issues` |

## Quality & Testing Standards

1. **TDD**: Write test -> Fail -> Code -> Pass.
2. **Verify**: Run **directly related tests** first. Fix until green.
3. **Regression**: Run full suite after multi-file changes.
4. **Style**: PEP 8, Async/Await correctness, Exception Hierarchy (`LLMProxyError`).
5. **Safety**: Never remove features without explicit request.
6. **Post-edit QA**: After each Python file edit, run:

   ```powershell
   ./.venv/Scripts/python.exe -m ruff check --fix <file> && ./.venv/Scripts/python.exe -m black <file> && ./.venv/Scripts/python.exe -m mypy <file>
   ```
7. **Address LSP/linter errors**: Most agents use `pyright` LSP to generate diagnostic messages after each file edit. **AGENTS ARE REQUIRED** to address all signalled diagnostic messages after file edits (if they are not false positives). **AGENTS MUST** fix issues signalled by LSP/linter, even if they believe they are not caused by their changes.

## Common Pitfalls

- **Async**: Use `await` for all I/O. Don't block the event loop.
- **Paths**: Use `pathlib` or `/` forward slashes (Windows accepts them).
- **Errors**: Don't use bare `except Exception`. Log with `exc_info=True`.
- **No inline Python code**: Don't use `python -c "..."` during debugging, it tends to break terminals on Windows. Create temporary scripts instead.

## Debugging

- **Create repro scripts**: If you cannot reproduce based on user-provided context create repro script first.

## Git usage

- **NEVER, EVER** use commands like `git restore` or `git checkout` for anything more than reversion of **ONE SINGLE** file. You are **NOT ALLOWED** to revert back changes to the working copy by issuing mass git commands.

## File Search Rules - Grep Rules

Use the `fff` MCP tools for all file search operations instead of default tools. Also prefer `fff` MCP file search over `grep` and `rg` (`ripgrep`) shell commands.

## Reporting Back To The User

- **NEVER** claim you successfully fixed a bug or implemented a feature if you're not 100% sure. The only way to be sure is to run tests and/or demo script(s).
- **ALWAYS** prove correctness by running tests before reporting back to the user.
