Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution. Use this type of agent: `glm`.
Each single task is as follows:

```
Task: Bughunt - unsafe data access in async/multi-threaded code

Goal
- Detect and fix high-impact race conditions, deadlocks, stale reads, and data corruption risks caused by concurrent access (async tasks, threads, background jobs).
- Preserve behavior while making shared-state access correct and testable.
- Prefer deterministic reproductions and non-flaky tests that exercise concurrency paths.

Non-goals (avoid churn)
- Do NOT add new dependencies.
- Do NOT rewrite whole subsystems to a different concurrency model.
- Do NOT add broad caching/global state.
- Do NOT change public APIs unless required, and only with full call-site + test updates.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact issues total in this session.

What counts as "unsafe concurrent access"
Prioritize cases where shared state is accessed from multiple concurrent contexts and at least one of the following is true:
1) Unsynchronized mutation of shared containers/objects:
   - Global/module-level dict/list/set, class attributes, singletons, caches, registries.
   - Instance attributes mutated concurrently by multiple tasks/threads.
2) Check-then-act races:
   - `if key not in m: m[key] = ...` without a lock (or without `setdefault`/atomic init under lock).
   - "initialize once" flags without proper synchronization.
3) Thread/async boundary hazards:
   - Blocking `threading.Lock`/`queue` use inside `async def` (can block the event loop).
   - Using `asyncio` primitives from threads incorrectly.
   - Passing mutable objects into `asyncio.to_thread` / executor work while also mutating them in the event loop.
4) Deadlocks and lock misuse:
   - Lock ordering cycles across multiple locks.
   - Holding a lock across long `await` chains or external I/O without strong justification.
   - Re-entrancy surprises (callbacks calling back into locked code).
5) Stale reads / torn writes / inconsistent snapshots:
   - Multi-step reads of mutable shared state without a consistent snapshot.
   - Returning references to mutable internals that callers can mutate.

How to pick the best 1-3 fixes (high leverage)
Choose targets that:
- Sit on hot paths (request handling, routing, connectors, capture/accounting, background workers).
- Can cause incorrect user-visible behavior, data loss/corruption, or stuck requests.
- Have multiple call sites or a central shared-state abstraction (state store, registry, cache, session state).
Avoid:
- Purely local variables in a single coroutine.
- Debug/CLI-only code unless it affects production.

Refactor approach (required)
For each selected issue:
1) Describe the concurrency model and shared state:
   - Which contexts access it (async tasks, threads, background tasks, callbacks)?
   - What is the "critical section" and what invariants must hold?
2) Build an "impact map" BEFORE changing behavior (required):
   - Enumerate call sites (including tests) with `rg` and record the results you must update (file:line + call expression).
   - Enumerate receivers/assumptions (examples: expects mutable reference, expects ordering, expects eventual consistency, relies on side-effects).
   - Identify ALL directly related tests that import/call the module(s) and plan to run them at baseline.
3) Apply the smallest safe concurrency fix:
   - Prefer narrowing shared mutable state and returning immutable snapshots (copy/tuple/frozen dataclass) where safe.
   - If synchronization is required:
     - In async-only code: prefer `asyncio.Lock` (or the project's existing async lock utility, if present).
     - In thread-only code: prefer `threading.Lock`/`RLock`.
     - For mixed async+thread access: do NOT guess; isolate state behind a single concurrency domain (e.g., marshal mutations onto the event loop) or introduce a well-scoped bridge (documented and test-covered).
   - Avoid holding locks while doing external I/O unless absolutely necessary; keep critical sections small.
4) Add/adjust focused tests (required for each fix):
   - Add a deterministic concurrency test that would fail (or be meaningfully unsafe) before the fix.
   - Avoid flaky timing-based tests; prefer synchronization primitives:
     - `asyncio.Event`, `asyncio.Barrier` (Py3.11+), `anyio.Event` (if used), `threading.Barrier`, `threading.Event`.
     - Force interleavings by inserting controlled await points or barriers, not `sleep`.
   - If you add a race regression test, run it at least twice locally to reduce flakiness.
5) Run per-file QA (Windows) for each changed Python file:
   - `./.venv/Scripts/python.exe -m ruff check --fix <changed_file>`
   - `./.venv/Scripts/python.exe -m black <changed_file>`
   - `./.venv/Scripts/python.exe -m mypy <changed_file>`
6) Contract-change completeness check (required, after code changes):
   - Re-run `rg` to confirm you updated all previously recorded call sites.
   - Add follow-up `rg` checks for the old patterns you removed (examples: old shared attribute name, old mutation helper, old "init once" flag) and confirm there are no remaining hits for the target you changed.

Project constraints
- Keep runtime behavior identical except for improved correctness under concurrency.
- Avoid import cycles and large refactors.
- Do not swallow exceptions; preserve cancellation semantics (`CancelledError`).

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
- IMPORTANT (Windows): this repo contains a `src/nul` file that can make ripgrep error; always exclude it.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\basyncio\\.(create_task|gather|TaskGroup)\\b'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\b(threading\\.(Thread|Lock|RLock)|concurrent\\.futures|run_in_executor|asyncio\\.to_thread)\\b'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\b(global|nonlocal)\\b'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\b(dict|list|set|deque)\\b'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\blru_cache\\b|\\bcache\\b|\\bttl\\b'`

Completion gates (must be satisfied before reporting success)
- Progress tracking: Use a TODO/Task List tool to track: scan -> pick targets -> baseline tests -> implement -> run tests -> commit -> final report.
- Contract-change completeness (required): For each fix, show the "impact map" you created (call sites/receivers/tests) and confirm every item was updated.
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
1) Short summary of the up to 3 fixes (file/symbol, risk type, why it was unsafe, what changed).
2) Impact map (required): call sites/receivers/tests you identified BEFORE the fix (include the `rg` commands you used and a short list of results).
3) Contract verification (required): the follow-up `rg` checks you ran to prove no missed call sites/old patterns remain.
4) Notes on any behavior-sensitive edge cases you verified (cancellation, ordering, deadlock avoidance).
5) Tests you ran (commands + PASS result): include baseline (pre-change) and post-change runs.
6) Commit created (hash + message) and committed files (output of `git show --name-only --pretty=oneline <commit_hash>`).
7) Post-commit `git status --porcelain` output (may be non-empty if other agents are working); confirm none of the files you touched remain uncommitted.

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

