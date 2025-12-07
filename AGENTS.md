<!-- KIRO-SPEC:START -->
# Kiro Spec-Driven Development

## When to Use Kiro Specs

**Suggest spec workflow** when request involves: new features, breaking changes, architecture shifts, complex integrations, or unclear requirements needing structured analysis.

**Code directly** for: quick fixes, simple bugs, trivial changes, or when user explicitly says "just code this".

## Kiro Commands (User-Triggered)

When working on specs, the user will invoke `/kiro:*` commands. Follow the instructions provided in each command's context.

**Workflow order**: `spec-init` → `spec-requirements` → `spec-design` → `spec-tasks` → `spec-impl`

**Spec-driven rule**: When a spec exists at `.kiro/specs/{feature}/`, no code edits until `requirements.md` and `design.md` are approved (check `spec.json` for approval status). Every task in `tasks.md` must reference at least one acceptance criterion from requirements.

**Key locations**:

- Specs: `.kiro/specs/{feature-name}/` (requirements.md, design.md, tasks.md, research.md)
- Steering (project memory): `.kiro/steering/` - load when generating specs
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
4. **Onboarding**: Open `@README.md` for fundamenal project description.
5. **Docs**: Check `docs/` for architecture deep-dives.

## Key Architecture Paths

| Path | Purpose |
|------|---------|
| `src/core/cli.py` | **Entry Point**. CLI args -> Config -> App Builder. |
| `src/core/app/stages/` | **Startup Logic**. Infrastructure -> Services -> Backends -> Controllers. |
| `src/connectors/` | **Backends**. Implementations for OpenAI, Gemini, Anthropic, etc. |
| `src/core/simulation/` | **Debugging**. Traffic replay & inspection tools (`capture_reader.py`). |
| `var/wire_captures_cbor/` | **Data**. Binary captures of all traffic (pair with `var/logs/`). |

## Commands & Workflow

**Rule**: Edit `pyproject.toml` for deps. **NO** manual `pip install`. **NO** emojis.

| Action | Command |
|--------|---------|
| **Test (Fast)** | `./.venv/Scripts/python.exe -m pytest` (skips slow/integration) |
| **Test (Full)** | `./.venv/Scripts/python.exe -m pytest -m "integration or unit"` |
| **Lint/Fix** | `./.venv/Scripts/python.exe -m ruff --fix check .` |
| **Format** | `./.venv/Scripts/python.exe -m black .` |
| **Inspect** | `./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py <file> --detect-issues` |

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

## Common Pitfalls

- **Async**: Use `await` for all I/O. Don't block the event loop.
- **Paths**: Use `pathlib` or `/` forward slashes (Windows accepts them).
- **Errors**: Don't use bare `except Exception`. Log with `exc_info=True`.
