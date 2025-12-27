Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - pytest slow tests optimization

Goal
- Reduce overall `pytest` suite runtime by speeding up the slowest tests.
- Keep test coverage, test precision, and test logic intact (no “making it faster by testing less”).
- Keep the suite 100% green after changes.

Non-goals (avoid churn / forbidden shortcuts)
- Do NOT skip/xfail/mark tests to avoid running them (including `-k`, `-m`, `@pytest.mark.skip`, `xfail`, changing `pyproject.toml` addopts).
- Do NOT remove assertions or materially weaken checks just to speed up.
- Do NOT add new dependencies or change packaging/config.
- Do NOT refactor broadly unless directly needed for performance.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Primary target: `./tests/` slow tests and their fixtures.
- You may optimize production code in `./src/` ONLY when it is the clear cause of slowness for the selected tests, and only with behavior-preserving changes.
- Fix up to TEN (10) slow tests total in this session.

Baseline measurement (required)
1) Record total suite time and top-20 slowest tests by running the FULL suite with timings enabled:
   - Use this exact command to capture total time + per-test durations:
     - `$sw=[System.Diagnostics.Stopwatch]::StartNew(); ./.venv/Scripts/python.exe -m pytest --durations=20 --durations-min=1; $sw.Stop(); "PYTEST_TOTAL_SECONDS=$([math]::Round($sw.Elapsed.TotalSeconds,2))"`
2) In your report, include:
   - The printed `PYTEST_TOTAL_SECONDS=...`
   - The `--durations=20` section (top-20 slow tests with times)

How to pick up to 10 tests from the slowest 20 (suggested criteria)
Pick tests that are BOTH slow and realistically optimizable without changing semantics:
- Prefer tests whose time is dominated by avoidable setup/teardown (fixtures, temp files, expensive initialization) or explicit sleeps/timeouts.
- Prefer tests that exercise the same expensive setup repeatedly (good candidates for fixture scoping/caching) and tests with obvious I/O that can be replaced by in-memory equivalents.
- If the #1 slowest is a deep integration test that is slow “by design”, pick 1 truly slow test + up to 2 easier wins from the top-20 that you can confidently optimize.
Avoid:
- Tests that are slow due to intentional end-to-end coverage and have no clear inefficiency.
- Changes that make tests less deterministic (racey timing, relying on wall-clock).

Optimization tactics (examples; use judgment)
- Fixture optimization:
  - Reduce fixture scope overhead by using `module`/`session` scope when safe (no state leakage; ensure cleanup).
  - Replace repeated heavy setup with cached/session resources, but keep strict isolation where required.
  - Use `tmp_path_factory` for shared temp roots when appropriate.
  - Prefer stubs/monkeypatching over real disk/network/clock usage, but preserve what the test is validating.
- Remove sleeps / tighten timeouts safely:
  - Replace `time.sleep(...)` with deterministic synchronization (events/queues) or polling with small bounded timeout.
  - For async: avoid blocking calls; use `await` + `asyncio.wait_for` as appropriate.
- Reduce unnecessary work:
  - Avoid generating huge payloads when a smaller representative payload exercises the same behavior.
  - If input size must be reduced, compensate with additional targeted assertions that preserve what the test is intended to prove.

Refactor approach (required)
For each selected test:
1) Capture its baseline duration from the `--durations=20` output.
2) Make the smallest change that speeds it up while keeping the test’s intent and checks intact.
3) Validate determinism: the test should not become flaky (avoid wall-clock dependence).
4) Run per-file QA (Windows) for each changed Python file:
   - `./.venv/Scripts/python.exe -m ruff check --fix <changed_file>`
   - `./.venv/Scripts/python.exe -m black <changed_file>`
   - `./.venv/Scripts/python.exe -m mypy <changed_file>`

Tests (required)
- Baseline (pre-change): run the FULL suite with timings (command above) BEFORE editing any file; it must be green. If baseline fails, STOP and report the failures; do NOT proceed with performance edits this iteration.
- Focused iteration: during development you may run ONLY the specific tests you’re changing to iterate quickly (e.g. `./.venv/Scripts/python.exe -m pytest <path>::<test_name>`), but you must still keep them green.
- Post-change: run the FULL suite again with timings (command above). Keep fixing until 100% green.
- In your report, include baseline and post-change full-suite runs (commands + PASS) and show before/after durations for the tests you targeted (from the `--durations=20` sections).

Git safety and commit rules (required)
- Git state (do not block on dirty): Record `git status --porcelain` before editing for context. If it is not empty, continue anyway; do NOT try to "clean" the tree (no stash/reset/checkout), and do NOT stage/commit unrelated changes.
- Branch/remote safety: Do NOT create branches, switch branches, detach HEAD, or do any operations on remotes.
  - Confirm you are on a normal branch (not detached): `git rev-parse --abbrev-ref HEAD` must NOT return `HEAD`.
  - Forbidden examples: `git checkout -b`, `git switch -c`, `git checkout <branch>`, `git switch <branch>`, `git pull`, `git push`, `git fetch`, `git remote ...`, `git submodule ...`, `git tag ...`.
- Git safety (required): Do NOT use git operations that can discard/rewrite/hide other agents' work (examples: `git reset --hard`, `git reset`, `git checkout .`, `git restore .`, `git clean -fd`, `git stash`, `git commit --amend`, `git rebase`, `git merge`).
  - If you must undo a broken change or abort the session, only restore files YOU modified, one-by-one with explicit paths: `git restore --source=HEAD -- <file>` (or `git checkout -- <file>`). No globs and never `.`.
- Commit (required if you changed any files): Create exactly ONE commit for this session at the end, after baseline + post-change full-suite tests are green; commit ONLY the files you changed for this session.
  - Do NOT create multiple commits. Do NOT commit early.
  - Forbidden: `git add .`, `git add -A`, `git add --all`, `git add -u`, `git commit -am`, `git commit -a`, `git stash`.
  - Stage explicitly: `git add <file1> <file2> ...`, then verify: `git diff --cached --name-only`.
  - End state: overall `git status --porcelain` may be non-empty (other agents), but none of the files you touched should remain modified or staged after your commit.

Deliverables / reporting (in your final response)
1) Baseline full-suite timing:
   - `PYTEST_TOTAL_SECONDS=...`
   - Top-20 slow tests list (`--durations=20` section)
2) Selected tests (up to 3):
   - Why you chose them (slowest vs easiest-win rationale)
   - Before/after timings (from durations output)
   - What you changed (test/fixture/code) and why it preserves test intent
3) Files changed.
4) Tests you ran:
   - Baseline full-suite (command + PASS)
   - Any focused runs you used to iterate (optional)
   - Post-change full-suite (command + PASS)
5) Commit created (hash + message) and committed files (output of `git show --name-only --pretty=oneline <commit_hash>`).
6) Post-commit `git status --porcelain` output; confirm none of the files you touched remain uncommitted.

Already fixed files (do not modify):
{list-of-fixed-files}
```

Orchestrator instructions (READ-ONLY)
- You are a READ-ONLY orchestrator: do not modify the repo. Do not run commands that write files (including formatting/linting/test runs). Only spawn subagents to perform edits, run tests, and commit.
- Branch/remote safety: Do NOT create/switch branches, detach HEAD, or do any operations on remotes.
- Concurrency note: The working tree may be dirty due to other agents; do NOT require a clean `git status`. Focus verification on whether the subagent ran the required tests and produced a commit that includes only the files it touched.
- Use a TODO/Task List tool to track: iteration counter, consecutive "no-fix" count, and post-run verification checks.
- Loop breaker: before spawning any subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating immediately.

Per-iteration checklist (for i = 1..50)
1) If the stop file exists: break.
2) (Read-only) Before spawning, record current branch: `git rev-parse --abbrev-ref HEAD` (must not be `HEAD`), record current HEAD: `git rev-parse HEAD`, and record `git status --porcelain` for context (may be non-empty).
3) Spawn exactly ONE subagent with the task prompt (replace `{list-of-fixed-files}` with your accumulated list).
4) After the subagent reports back, verify (read-only checks + report review):
   - Branch/HEAD safety: `git rev-parse --abbrev-ref HEAD` is unchanged and not `HEAD`.
   - If the subagent changed any files:
     - Tests: it ran baseline and post-change FULL-suite runs with timings, and both were green (commands + PASS result are required).
     - Git: it reported exactly ONE commit hash for its work.
       - Verify the commit exists: `git cat-file -t <commit_hash>` returns `commit`.
       - Verify committed files: `git show --name-only --pretty=oneline <commit_hash>` matches the subagent's reported touched files.
       - Optional sanity check: `git merge-base --is-ancestor <commit_hash> HEAD` succeeds.
   - If the subagent made no changes: do NOT require tests/commit; count this as a "no-fix found" iteration.
5) If (and only if) the subagent changed files and any required gate is missing (baseline tests missing/not green, post-change tests not green, no commit, commit hash missing/mismatch, commit includes extra files): before spawning the follow-up subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating. If the violation would require forbidden git operations to fix (branch switched/detached, history rewritten, or a bad commit that cannot be corrected without rewriting history), STOP iterating and report. Otherwise spawn a follow-up subagent with brief instructions to fix ONLY that (run/fix tests and/or commit hygiene). Do not fix it yourself.
6) If the subagent failed to find at least one performance win to commit in three consecutive iterations: stop iterating (job done).
7) Append newly committed files to the "already fixed files" list before the next iteration (only when a commit was created).

