# Task: Code maintenance - exception hygiene and logging

## Goal

- Improve maintainability and debuggability by replacing overly broad exception handling with precise exceptions and consistent logging.
- Ensure exception handling follows project standards (LLMProxyError hierarchy, async correctness, logging with exc_info=True).
- IMPORTANT: An exception-handling refactor is not "done" until ALL dependent call sites/receivers and ALL directly related tests are updated to the new behavior/contract.

## Non-goals (avoid churn)

- Do NOT change runtime behavior or error surfaces unless the current behavior is clearly unsafe (e.g., bare except swallowing errors silently).
- Do NOT refactor large control flow just to "clean up" exceptions.
- Do NOT touch files listed in "already fixed files".

## Scope and limits

- Scan only ./src/ and its subfolders.
- Fix up to THREE (3) high-impact cases total in this session.

## What counts as "exception hygiene" issues

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

## How to pick the best 1-3 refactors (high leverage)

Choose handlers that:
- Sit on boundaries (connectors, service layer, controllers).
- Affect multiple call sites or error reporting paths.
- Make debugging painful due to lost context.
Avoid:
- One-off helpers with a single local call site unless the current handling is actively dangerous.

## Refactor approach (required)

For each selected handler:
1) Identify the expected exception types and use the most precise type(s) available.
2) Preserve behavior:
   - If a handler must swallow an error, add logging with context and `exc_info=True`.
   - If rethrowing, use exception chaining (`raise ... from err`) where appropriate.
3) Keep async correctness (no blocking I/O in handlers).
4) Build an "impact map" BEFORE changing behavior (required):
   - Enumerate call sites (including tests) with `rg` and record the results you must update (file:line + call expression).
   - Enumerate receivers and assumptions about failure modes (examples: catching `Exception`, expecting `None`, relying on specific log text, relying on a specific exception type/message).
   - Identify ALL directly related tests that import/call the function/module and plan to run them at baseline.
5) Update tests and call sites to reflect the stronger error semantics (required):
   - Update call sites AND any intermediate wrappers that forward/transform exceptions.
   - Avoid accidental behavior changes like converting `CancelledError` into a generic failure or changing return-on-error behavior without updating its callers/tests.
6) Add focused unit tests if behavior is subtle or error handling is important.
7) After each file edit you will be provided with LSP server diagnostic/linting output. Fix all of such issues reported immedietelty even if you think they are not related to your changes.
8) Contract-change completeness check (required, after code changes):
   - Re-run `rg` to confirm you updated all previously recorded call sites.
   - Add a follow-up `rg` for the old patterns you removed (examples: old exception class name, old catch-all handler, old return-on-error sentinel) and confirm there are no remaining hits for the target you changed.

## Project constraints

- Use codebase standards and existing conventions.
- Prefer `LLMProxyError` and existing exception classes where appropriate.
- Avoid import cycles.
- Keep runtime behavior identical unless there is a clear bug fix aligned with the hygiene improvements.

## Completion gates (must be satisfied before reporting success)

- Progress tracking: Use a TODO/Task List tool to track: scan -> pick targets -> implement -> run related tests -> commit -> final report.
- Contract-change completeness (required): For each changed handler, show the "impact map" you created (call sites/receivers/tests) and confirm every item was updated.
- Git state (do not block on dirty): Record `git status --porcelain` before editing for context. If it is not empty, continue anyway; do NOT try to "clean" the tree (no stash/reset/checkout), and do NOT stage/commit unrelated changes.
- Branch/remote safety (required): Do NOT create branches, switch branches, detach HEAD, or do any operations on remotes.
  - Confirm you are on a normal branch (not detached): `git rev-parse --abbrev-ref HEAD` must NOT return `HEAD`.
  - Forbidden examples: `git checkout -b`, `git switch -c`, `git checkout <branch>`, `git switch <branch>`, `git pull`, `git push`, `git fetch`, `git remote ...`, `git submodule ...`, `git tag ...`.
- Tests (required): Identify ALL test files directly related to the files you plan to change, then run them at baseline (pre-change) and again after your changes.
  - Find related tests by searching `tests/` for imports/references to the changed module(s) and key symbols.
  - Baseline (pre-change): run BEFORE editing any file; they must be green. If they fail at baseline, do NOT proceed on this target; pick a different target or STOP and report.
  - Post-change: re-run the same tests after your changes; if any fail, keep fixing and re-run until all pass.
  - Run with: `./.venv/Scripts/python.exe -m pytest <test_file1> <test_file2> ...`
  - Abort protocol: if you cannot get the post-change tests green after 3 fix->test cycles, undo ONLY your session's changes by unstaging/restoring the explicit paths you touched (no globs), then report.
    - If needed: `git restore --staged -- <file>` then `git restore --source=HEAD -- <file>`
- Git safety (required): Do NOT use git operations that can discard/rewrite/hide other agents' work (examples: `git reset --hard`, `git reset`, `git checkout .`, `git restore .`, `git clean -fd`, `git stash`, `git commit --amend`, `git rebase`, `git merge`).
  - If you must undo a broken change or abort the session, only restore files YOU modified, one-by-one with explicit paths: `git restore --source=HEAD -- <file>` (or `git checkout -- <file>`). No globs and never `.`.
- Commit (required if you changed any files): Create exactly ONE commit for this session at the end, after baseline + post-change related tests are green; commit ONLY the files you changed for this session.
  - Do NOT create multiple commits. Do NOT commit early.
  - Forbidden: `git add .`, `git add -A`, `git add --all`, `git add -u`, `git commit -am`, `git commit -a`, `git stash`.
  - Stage explicitly: `git add <file1> <file2> ...`, then verify: `git diff --cached --name-only`.
  - End state: overall `git status --porcelain` may be non-empty (other agents), but none of the files you touched should remain modified or staged after your commit.

## Deliverables / reporting (in your final response)

1) Short summary of the up to 3 fixes (function name, file, old handler -> new handler, why it's materially better).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified.
4) Impact map (required): call sites/receivers/tests you identified BEFORE changing behavior (include the `rg` commands you used and a short list of results).
5) Contract verification (required): the follow-up `rg` checks you ran to prove no missed call sites/old patterns remain.
6) Tests you ran (commands + PASS result): include baseline (pre-change) and post-change runs.
7) Commit created (hash + message) and committed files (output of `git show --name-only --pretty=oneline <commit_hash>`).
8) Post-commit `git status --porcelain` output (may be non-empty if other agents are working); confirm none of the files you touched remain uncommitted.
9) Make sure you removed any temporary scripts you created during the process.
10) Do not create any report/summary file, only display it.

## Already fixed files (do not modify): 

{list-of-fixed-files}
