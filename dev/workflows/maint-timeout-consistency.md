Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - timeout consistency for outbound I/O

Goal
- Improve reliability by making outbound I/O timeouts explicit and consistent (avoid accidental infinite hangs).
- Prefer using existing timeout configuration/constants already present in the codebase.
- IMPORTANT: A timeout refactor is not "done" until ALL dependent call sites/receivers and ALL directly related tests are updated to the new timeout wiring/contract.

Non-goals (avoid churn)
- Do NOT invent new timeout values out of thin air.
- Do NOT change retry strategy, backoff, or request semantics.
- Do NOT make broad API signature refactors; prefer localized changes.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

What counts as a "timeout consistency" issue
Prioritize cases where code performs outbound I/O and:
1) Uses no timeout where a timeout is expected:
   - HTTP client calls with no timeout argument and no client-level timeout configured
2) Explicitly disables timeouts:
   - `timeout=None`, `httpx.Timeout(None)`, or equivalent
3) Uses inconsistent hard-coded timeout literals across the same subsystem:
   - multiple different numeric values for essentially the same operation without rationale

How to pick the best 1-3 refactors (high leverage)
Choose call sites that:
- Are in connectors/backends, routing, or any external network boundary.
- Are on request/streaming hot paths.
- Have multiple similar call sites that can be unified to one existing config value.
Avoid:
- Very low-risk, rarely executed code paths unless they are an obvious hang risk.

Refactor approach (required)
For each selected case:
1) Locate the subsystem's existing timeout source:
   - A config field, settings object, or module-level constant already used elsewhere.
2) Build an "impact map" BEFORE changing the call wiring (required):
   - Enumerate call sites (including tests) that share the same client/config path and record what must be updated (file:line + call expression).
   - Enumerate receivers/assumptions (examples: wrappers that forward `timeout=...`, factories that build `httpx.AsyncClient`, mocks/fixtures asserting specific kwargs).
   - Identify ALL directly related tests that import/call the affected module(s) and plan to run them at baseline.
3) Apply the minimal safe fix:
   - Replace hard-coded literals with the existing timeout constant/config value.
   - If a call has no timeout and the same subsystem already uses a default timeout elsewhere, thread that same timeout into the call.
   - If there is no existing timeout source to reuse safely, DO NOT invent a new number; skip the change and report it as "found but not safely fixable without product decision".
4) Preserve behavior as much as possible:
   - Do not add new timeouts unless you can tie them directly to existing project configuration.
5) Add/update focused unit tests where the timeout value is part of behavior (e.g., ensure it is passed to the client call).
6) Contract-change completeness check (required, after code changes):
   - Re-run `rg` to confirm you updated all previously recorded call sites.
   - Add follow-up `rg` checks for the old patterns you removed (examples: the specific hard-coded literal(s), `timeout=None`, old config key name) and confirm there are no remaining hits for the target you changed.
7) After each file edit you will be provided with LSP server diagnostic/linting output. Fix all of such issues reported even if you think they are not related to your changes.   
8) Run targeted tests plus per-file QA (Windows):
   - `./.venv/Scripts/python.exe -m ruff check --fix <changed_file>`
   - `./.venv/Scripts/python.exe -m black <changed_file>`
   - `./.venv/Scripts/python.exe -m mypy <changed_file>`
   - `./.venv/Scripts/python.exe -m pytest <relevant_tests>`

Project constraints
- Use existing config patterns and staging/DI conventions.
- Avoid import cycles.
- Keep runtime behavior identical unless you can justify that a missing timeout is an existing correctness bug and you are reusing an existing configured value.

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
- IMPORTANT (Windows): this repo contains a `src/nul` file that can make ripgrep error; always exclude it.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\btimeout\\s*=\\s*None\\b'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\bhttpx\\.Timeout\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\bhttpx\\.(Client|AsyncClient)\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\brequests\\.(get|post|put|delete|request)\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\b(timeout|connect_timeout|read_timeout|write_timeout)\\s*='`

Completion gates (must be satisfied before reporting success)
- Progress tracking: Use a TODO/Task List tool to track: scan -> pick targets -> implement -> run related tests -> commit -> final report.
- Contract-change completeness (required): For each timeout change, show the "impact map" you created (call sites/receivers/tests) and confirm every item was updated.
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

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (call site, file, old timeout -> new timeout source, why it's materially better).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified (streaming, retries, exception propagation).
4) Impact map (required): call sites/receivers/tests you identified BEFORE changing timeout wiring (include the `rg` commands you used and a short list of results).
5) Contract verification (required): the follow-up `rg` checks you ran to prove no missed call sites/old patterns remain.
6) Tests you ran (commands + PASS result): include baseline (pre-change) and post-change runs.
7) Any "found but not safely fixable without product decision" items (file + why).
8) Commit created (hash + message) and committed files (output of `git show --name-only --pretty=oneline <commit_hash>`).
9) Post-commit `git status --porcelain` output (may be non-empty if other agents are working); confirm none of the files you touched remain uncommitted.

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
     - Contract-change completeness: it included an "impact map" (call sites/receivers/tests) and follow-up `rg` checks showing no missed call sites/old patterns remain.
     - Tests: it ran baseline (pre-change) and post-change runs of ALL directly related tests and they passed (commands + PASS result are required).
     - Git: it reported exactly ONE commit hash for its work.
       - Verify the commit exists: `git cat-file -t <commit_hash>` returns `commit`.
       - Verify committed files: `git show --name-only --pretty=oneline <commit_hash>` matches the subagent's reported touched files.
       - Optional sanity check: `git merge-base --is-ancestor <commit_hash> HEAD` succeeds.
   - If the subagent made no changes: do NOT require tests/commit; count this as a "no-fix found" iteration.
5) If (and only if) the subagent changed files and any required gate is missing (impact map missing, follow-up `rg` checks missing, baseline tests missing/not green, post-change tests not green, no commit, commit hash missing/mismatch, commit includes extra files): before spawning the follow-up subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating. If the violation would require forbidden git operations to fix (branch switched/detached, history rewritten, or a bad commit that cannot be corrected without rewriting history), STOP iterating and report. Otherwise spawn a follow-up subagent with brief instructions to fix ONLY that (complete missed call-site audit + update remaining call sites/tests and/or run/fix tests and/or commit hygiene). Do not fix it yourself.
6) If the subagent failed to find at least one issue to fix in three consecutive iterations: stop iterating (job done).
7) Append newly committed files to the "already fixed files" list before the next iteration (only when a commit was created).
