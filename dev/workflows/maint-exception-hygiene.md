Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - exception hygiene and logging

Goal
- Improve maintainability and debuggability by replacing overly broad exception handling with precise exceptions and consistent logging.
- Ensure exception handling follows project standards (LLMProxyError hierarchy, async correctness, logging with exc_info=True).

Non-goals (avoid churn)
- Do NOT change runtime behavior or error surfaces unless the current behavior is clearly unsafe (e.g., bare except swallowing errors silently).
- Do NOT refactor large control flow just to "clean up" exceptions.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

What counts as "exception hygiene" issues
Prioritize cases that:
1) Use bare or too-broad handlers:
   - `except:`
   - `except Exception:`
   - `except BaseException:`
2) Swallow exceptions with no logging or context:
   - `except ...: pass`
   - `except ...: return None` or default value without logging
3) Log without stack trace:
   - `logger.error("...", exc_info=False)` or missing `exc_info=True` for unexpected errors
4) Catch/raise patterns that hide root causes:
   - `raise SomeError("...")` without chaining or context when rethrowing a lower-level exception

How to pick the best 1-3 refactors (high leverage)
Choose handlers that:
- Sit on boundaries (connectors, service layer, controllers).
- Affect multiple call sites or error reporting paths.
- Make debugging painful due to lost context.
Avoid:
- One-off helpers with a single local call site unless the current handling is actively dangerous.

Refactor approach (required)
For each selected handler:
1) Identify the expected exception types and use the most precise type(s) available.
2) Preserve behavior:
   - If a handler must swallow an error, add logging with context and `exc_info=True`.
   - If rethrowing, use exception chaining (`raise ... from err`) where appropriate.
3) Keep async correctness (no blocking I/O in handlers).
4) Update tests and call sites to reflect the stronger error semantics when needed.
5) Add focused unit tests if behavior is subtle or error handling is important.

Project constraints
- Use codebase standards and existing conventions.
- Prefer `LLMProxyError` and existing exception classes where appropriate.
- Avoid import cycles.
- Keep runtime behavior identical unless there is a clear bug fix aligned with the hygiene improvements.

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
- IMPORTANT (Windows): this repo contains a `src/nul` file that can make ripgrep error; always exclude it.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'except\\s*:'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'except\\s+Exception|except\\s+BaseException'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'exc_info\\s*=\\s*False|logger\\.error\\('`

Completion gates (must be satisfied before reporting success)
- Progress tracking: Use a TODO/Task List tool to track: scan -> pick targets -> implement -> run related tests -> commit -> final report.
- Start clean: Run `git status --porcelain` before editing. If it is not empty, STOP and report back (do not stash/reset/checkout the whole tree).
- Branch/remote safety (required): Do NOT create branches, switch branches, detach HEAD, or do any operations on remotes.
  - Confirm you are on a normal branch (not detached): `git rev-parse --abbrev-ref HEAD` must NOT return `HEAD`.
  - Forbidden examples: `git checkout -b`, `git switch -c`, `git checkout <branch>`, `git switch <branch>`, `git pull`, `git push`, `git fetch`, `git remote ...`, `git submodule ...`, `git tag ...`.
- Tests (required): Run ALL test files directly related to the files you changed; they must be green before you finish.
  - Find related tests by searching `tests/` for imports/references to the changed module(s) and key symbols.
  - Run with: `./.venv/Scripts/python.exe -m pytest <test_file1> <test_file2> ...`
  - If any fail: keep fixing and re-run until all pass.
- Git safety (required): Do NOT use git operations that can discard/rewrite other agents' work (examples: `git reset --hard`, `git checkout .`, `git restore .`, `git clean -fd`, `git commit --amend`, `git rebase`, `git merge`).
  - If you must undo a broken change, only revert ONE file you damaged: `git restore --source=HEAD -- <file>` (or `git checkout -- <file>`). No globs.
- Commit (required if you changed any files): After related tests are green, commit ONLY the files you changed for this session.
  - Forbidden: `git add .`, `git add -A`, `git commit -am`.
  - Stage explicitly: `git add <file1> <file2> ...`, then verify: `git diff --cached --name-only`.
  - End state must be clean: `git status --porcelain` is empty.

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (function name, file, old handler -> new handler, why it's materially better).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified.
4) Tests you ran (commands + result).
5) Commit created (hash + message) and committed files (output of `git show --name-only --pretty=oneline -1`).
6) Post-commit `git status --porcelain` output (should be empty).

Already fixed files (do not modify):
{list-of-fixed-files}
```

Orchestrator instructions (READ-ONLY)
- You are a READ-ONLY orchestrator: do not modify the repo. Do not run commands that write files (including formatting/linting/test runs). Only spawn subagents to perform edits, run tests, and commit.
- Branch/remote safety: Do NOT create/switch branches, detach HEAD, or do any operations on remotes.
- Use a TODO/Task List tool to track: iteration counter, consecutive "no-fix" count, and post-run verification checks.
- Loop breaker: before spawning any subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating immediately.

Per-iteration checklist (for i = 1..50)
1) If the stop file exists: break.
2) (Read-only) Before spawning, record current branch: `git rev-parse --abbrev-ref HEAD` (must not be `HEAD`), and confirm the working tree is clean: `git status --porcelain` is empty. If not clean, STOP iterating.
3) Spawn exactly ONE subagent with the task prompt (replace `{list-of-fixed-files}` with your accumulated list).
4) After the subagent reports back, verify (read-only checks + report review):
   - Branch/HEAD safety: `git rev-parse --abbrev-ref HEAD` is unchanged and not `HEAD`.
   - Working tree: `git status --porcelain` is empty.
   - If the subagent changed any files:
     - Tests: it ran ALL directly related tests and they passed (commands + PASS result are required).
     - Git: it created a commit that includes ONLY the files it changed for this session.
       - Run `git show --name-only --pretty=oneline -1` and confirm it matches the subagent's reported files.
   - If the subagent made no changes: do NOT require tests/commit; count this as a "no-fix found" iteration.
5) If (and only if) the subagent changed files and tests were not run / not green / no commit / commit includes extra files / dirty status: before spawning the follow-up subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating. Otherwise spawn a follow-up subagent with brief instructions to fix ONLY that (run/fix tests and/or commit hygiene). Do not fix it yourself.
6) If the subagent failed to find at least one issue to fix in three consecutive iterations: stop iterating (job done).
7) Append newly committed files to the "already fixed files" list before the next iteration (only when a commit was created).
