Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - fix unguarded logger calls (single-file sweep)

Goal
- Improve performance by guarding log calls that eagerly evaluate expensive strings/work (especially f-strings and `.format(...)`) when the log level is disabled.
- Keep runtime behavior identical (same logs at enabled levels; no message content changes).

Non-goals (avoid churn)
- Do NOT introduce new functionality or change external behavior.
- Do NOT add new dependencies or change packaging/config.
- Do NOT refactor large control flow just to "clean up" logging.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Choose EXACTLY ONE (1) Python file under `src/` (and its subfolders) that is not in "already fixed files" and contains at least one unguarded logger call.
- Fix ALL instances of unguarded logger calls in that file.
- Do NOT create new files, scripts, or do mass edits across the repo.
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.

What counts as "unguarded logger calls"
Prioritize logger calls that eagerly compute work when disabled, such as:
1) f-strings: `logger.debug(f\"...\")`, `logger.info(f\"...\")`, `logger.warning(f\"...\")`
2) `.format(...)` or string building in arguments: `logger.info(\"...\".format(...))`, `logger.info(\"\".join(...))`, `logger.info(json.dumps(...))`
3) expensive computations inside the logger call args that run even when the level is off

Guarding rule (required)
- Only add guards where the message computation is eager/expensive, typically:
  - `if logger.isEnabledFor(logging.DEBUG): logger.debug(...)`
  - `if logger.isEnabledFor(logging.INFO): logger.info(...)`
  - `if logger.isEnabledFor(logging.WARNING): logger.warning(...)`
- Do NOT guard `logger.error(...)` / `logger.exception(...)` unless you have a strong reason (they are typically important and not disabled in prod).
- Prefer converting to lazy logging style (e.g., `logger.debug(\"x=%s\", x)`) when it preserves the message meaning and is clearly safe.

Refactor approach (required)
1) Pick one file with at least one unguarded call (not already fixed).
2) Replace ALL unguarded calls in that file with guarded calls and/or lazy logging formatting.
3) Keep indentation and control flow minimal.
4) Run per-file QA (Windows):
   - `./.venv/Scripts/python.exe -m ruff check --fix <changed_file>`
   - `./.venv/Scripts/python.exe -m black <changed_file>`
   - `./.venv/Scripts/python.exe -m mypy <changed_file>`

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
- IMPORTANT (Windows): this repo contains a `src/nul` file that can make ripgrep error; always exclude it.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'logger\\.(debug|info|warning)\\(f\"|logger\\.(debug|info|warning)\\(.*\\.format\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'logger\\.(debug|info|warning)\\(.*(json\\.dumps|model_dump|join\\(|re\\.)'`
  - Optional helper script (if helpful): `./.venv/Scripts/python.exe dev/scripts/find_unguarded_logger_calls.py`

Completion gates (must be satisfied before reporting success)
- Progress tracking: Use a TODO/Task List tool to track: scan -> pick file -> baseline tests -> implement -> run tests -> commit -> final report.
- Start clean: Run `git status --porcelain` before editing. If it is not empty, STOP and report back (do not stash/reset/checkout the whole tree).
- Branch/remote safety (required): Do NOT create branches, switch branches, detach HEAD, or do any operations on remotes.
  - Confirm you are on a normal branch (not detached): `git rev-parse --abbrev-ref HEAD` must NOT return `HEAD`.
  - Forbidden examples: `git checkout -b`, `git switch -c`, `git checkout <branch>`, `git switch <branch>`, `git pull`, `git push`, `git fetch`, `git remote ...`, `git submodule ...`, `git tag ...`.
- Tests (required): Identify ALL test files directly related to the file you plan to change, then run them at baseline (pre-change) and again after your changes.
  - Find related tests by searching `tests/` for imports/references to the changed module(s) and key symbols.
  - Baseline (pre-change): run BEFORE editing any file; they must be green. If they fail at baseline, do NOT proceed on this target; pick a different target or STOP and report.
  - Post-change: re-run the same tests after your changes; if any fail, keep fixing and re-run until all pass.
  - Run with: `./.venv/Scripts/python.exe -m pytest <test_file1> <test_file2> ...`
  - Abort protocol: if you cannot get the post-change tests green after 3 fix->test cycles, restore only the files you changed (explicit paths, no globs) until `git status --porcelain` is clean, then report.
- Git safety (required): Do NOT use git operations that can discard/rewrite/hide other agents' work (examples: `git reset --hard`, `git reset`, `git checkout .`, `git restore .`, `git clean -fd`, `git stash`, `git commit --amend`, `git rebase`, `git merge`).
  - If you must undo a broken change or abort the session, only restore files YOU modified, one-by-one with explicit paths: `git restore --source=HEAD -- <file>` (or `git checkout -- <file>`). No globs and never `.`.
- Commit (required if you changed any files): Create exactly ONE commit for this session at the end, after baseline + post-change related tests are green; commit ONLY the file you changed for this session.
  - Do NOT create multiple commits. Do NOT commit early.
  - Forbidden: `git add .`, `git add -A`, `git add --all`, `git add -u`, `git commit -am`, `git commit -a`, `git stash`.
  - Stage explicitly: `git add <file>`, then verify: `git diff --cached --name-only`.
  - End state must be clean: `git status --porcelain` is empty.

Deliverables / reporting (in your final response)
1) File changed and what guarding pattern was applied.
2) Tests you ran (commands + PASS result): include baseline (pre-change) and post-change runs.
3) Commit created (hash + message) and committed files (output of `git show --name-only --pretty=oneline <commit_hash>`).
4) Post-commit `git status --porcelain` output (should be empty).

Already fixed files (do not modify):
{list-of-fixed-files}
```

Orchestrator instructions (READ-ONLY)
- You are a READ-ONLY orchestrator: do not modify the repo. Do not run commands that write files (including formatting/linting/test runs). Only spawn subagents to perform edits, run tests, and commit.
- Branch/remote safety: Do NOT create/switch branches, detach HEAD, or do any operations on remotes.
- Concurrency note: This workflow assumes exclusive access to the working tree. Do NOT run concurrently with other workflows in the same clone; use separate clones/worktrees for parallel runs.
- Use a TODO/Task List tool to track: iteration counter, consecutive "no-fix" count, and post-run verification checks.
- Loop breaker: before spawning any subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating immediately.

Per-iteration checklist (for i = 1..50)
1) If the stop file exists: break.
2) (Read-only) Before spawning, record current branch: `git rev-parse --abbrev-ref HEAD` (must not be `HEAD`), record current HEAD: `git rev-parse HEAD`, and confirm the working tree is clean: `git status --porcelain` is empty. If not clean, STOP iterating.
3) Spawn exactly ONE subagent with the task prompt (replace `{list-of-fixed-files}` with your accumulated list).
4) After the subagent reports back, verify (read-only checks + report review):
   - Branch/HEAD safety: `git rev-parse --abbrev-ref HEAD` is unchanged and not `HEAD`.
   - Working tree: `git status --porcelain` is empty.
   - If the subagent changed any files:
     - Tests: it ran baseline (pre-change) and post-change runs of ALL directly related tests and they passed (commands + PASS result are required).
     - Git: it created exactly ONE new commit on top of the recorded HEAD, and it reported the commit hash.
       - Verify `git rev-parse HEAD` matches the reported hash and differs from the recorded HEAD.
       - Verify one-commit rule: `git rev-parse HEAD^` equals the recorded HEAD.
       - Run `git show --name-only --pretty=oneline <commit_hash>` and confirm it matches the subagent's reported files.
   - If the subagent made no changes: do NOT require tests/commit; count this as a "no-fix found" iteration.
5) If (and only if) the subagent changed files and any required gate is missing (baseline tests missing/not green, post-change tests not green, no commit, commit hash missing/mismatch, more than one commit created, commit includes extra files, dirty status): before spawning the follow-up subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating. If the violation would require forbidden git operations to fix (branch switched/detached, multiple commits created, history rewritten), STOP iterating and report. Otherwise spawn a follow-up subagent with brief instructions to fix ONLY that (run/fix tests and/or commit hygiene). Do not fix it yourself.
6) If the subagent failed to find at least one issue to fix in three consecutive iterations: stop iterating (job done).
7) Append newly committed files to the "already fixed files" list before the next iteration (only when a commit was created).
