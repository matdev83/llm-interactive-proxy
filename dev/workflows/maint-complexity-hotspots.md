Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - reduce complexity hotspots (behavior-preserving)

Goal
- Improve maintainability and ease of safe edits by reducing cyclomatic complexity in a small number of high-impact functions.
- Preserve runtime behavior exactly (no new functionality).

Non-goals (avoid churn)
- Do NOT change external API behavior or public contracts.
- Do NOT introduce new dependencies.
- Do NOT do broad rewrites; keep refactors localized and reviewable.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

How to find complexity hotspots (choose one approach)
Option A (preferred): Ruff complexity rule
- Run: `./.venv/Scripts/python.exe -m ruff check src --select C901`

Option B: Existing project tooling
- Inspect existing analysis artifacts like `complexity_analysis.json` or run `./.venv/Scripts/python.exe dev/scripts/analyze_complexity.py` (use `--help` first).

How to pick the best 1-3 refactors (high leverage)
Choose functions that:
- Have good test coverage or clear unit-test seams.
- Are central (controllers, translators, connectors, services).
- Are hard to reason about due to deep nesting or long chains of conditionals.
Avoid:
- Functions with unclear side effects or very sparse tests unless the refactor is extremely mechanical.

Refactor approach (required)
For each selected hotspot:
1) Keep the public signature stable unless a change is strictly internal and clearly safe.
2) Reduce complexity by extracting small helper functions with clear names and tight responsibilities.
3) Prefer early returns and guard clauses over deep nesting where behavior is identical.
4) Keep exceptions, logging, and edge-case handling identical.
5) Add/adjust focused unit tests only where needed to prove equivalence.
6) Run per-file QA (Windows):
   - `./.venv/Scripts/python.exe -m ruff check --fix <changed_file>`
   - `./.venv/Scripts/python.exe -m black <changed_file>`
   - `./.venv/Scripts/python.exe -m mypy <changed_file>`
7) Run only directly related tests (do NOT run the full suite).

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
- IMPORTANT (Windows): this repo contains a `src/nul` file that can make ripgrep error; always exclude it.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'noqa: C901|C901'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'def\\s+\\w+\\(.*\\):'`

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
1) Short summary of the up to 3 refactors (function, file, what was extracted, why it's materially better).
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
