Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - performance bughunt (safe optimizations)

Goal
- Improve execution performance (CPU, latency, memory) by removing clear inefficiencies in hot paths.
- Prefer algorithmic improvements (better complexity) and elimination of repeated work/allocation.
- Keep runtime behavior identical.

Non-goals (avoid churn)
- Do NOT introduce new functionality or change external behavior.
- Do NOT add new dependencies or change packaging/config.
- Do NOT perform large refactors, stylistic rewrites, or speculative micro-optimizations.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

Performance measurement protocol (required)
- You MUST create a temporary measurement script and use it to measure baseline performance before making changes.
  - Put it under `dev/scripts/_tmp/` (create the folder if missing), e.g. `dev/scripts/_tmp/perf_measure_<topic>.py`.
  - Do NOT commit this script. You MUST delete it before finishing (success or abort).
- The script must exercise the suspect code path with representative inputs and run it in a loop:
  - Warm up first (e.g., 1-2 short warmup runs) to avoid first-run noise.
  - Use a reasonable iteration count (choose `iterations` so the timed portion takes ~2-10 seconds).
  - Measure with `time.perf_counter()` and print total time and per-iteration time.
  - Avoid external I/O (network/disk). If the hot path normally does I/O, stub/mock it so you measure CPU/alloc work.
- Run the script twice at baseline (pre-change) and record the outputs.
- After EACH optimization attempt, re-run the same script twice and compare against baseline (use the best or median run).
  - Treat tiny deltas as noise; target a clearly measurable improvement (rule of thumb: >5%).
- If you cannot achieve any measurable improvement after up to THREE (3) optimization attempts for a target, you MUST undo
  all changes for that target and move on (do not commit regressions or no-gain changes).

What counts as "performance issues" (examples)
Prioritize cases that are likely on hot paths (per-request, per-stream chunk/token, or loops over large data) and that have a clear, low-risk improvement:
1) Unnecessary copying or serialization:
   - `copy.deepcopy(...)` where a shallow copy, immutability, or a smaller targeted copy is sufficient
   - repeated `json.dumps` / `model_dump` / `dict(...)` conversions inside loops
2) Poor algorithmic complexity:
   - `O(n^2)` patterns (nested loops, repeated linear searches like `x in some_list` in loops)
   - repeated `.index()` / `.count()` / repeated scans over the same list/sequence
3) Repeated expensive setup work:
   - compiling regexes repeatedly (`re.compile`) instead of reusing a compiled pattern
   - repeated parsing/validation of the same input when it can be done once upstream
4) Inefficient data structures:
   - list membership checks where a `set` is appropriate (but preserve ordering/duplicates semantics when required)
   - building dicts via `{**a, **b}` repeatedly in loops
5) String/bytes inefficiencies:
   - repeated string concatenation in loops (`s += ...`) where `''.join(...)` is clearer/faster
   - encoding/decoding repeatedly in hot loops
6) Avoidable allocations:
   - building full lists where generators/iterators are sufficient (only when it does not change behavior)

How to pick the best 1-3 fixes (high leverage)
Choose targets that:
- Sit on request/streaming boundaries (connectors, streaming processors, routing, adapters).
- Are inside loops or called frequently.
- Have a clear correctness story (same outputs, same exceptions, same ordering/semantics).
Avoid:
- Micro-tweaks with unclear impact (e.g., swapping list comprehension vs loop) unless it removes an obvious big inefficiency.
- Changes that alter ordering, hashing, timing, or side effects without tests proving equivalence.

Refactor approach (required)
For each selected issue:
1) Identify the current bottleneck pattern and why it is inefficient.
2) Apply the smallest safe change that improves it:
   - Prefer reducing complexity or eliminating repeated work.
   - Do not add new third-party deps.
3) Validate behavior:
   - Update/add focused tests if needed for tricky semantics (ordering, exceptions, streaming).
4) After each file edit you will be provided with LSP server diagnostic/linting output. Fix all of such issues reported even if you think they are not related to your changes.   
5) Run per-file QA (Windows) for each changed Python file:
   - `./.venv/Scripts/python.exe -m ruff check --fix <changed_file>`
   - `./.venv/Scripts/python.exe -m black <changed_file>`
   - `./.venv/Scripts/python.exe -m mypy <changed_file>`
6) Run only directly related tests (do NOT run the full suite) and keep fixing until green.

Project constraints
- Keep runtime behavior identical; performance changes must be behavior-preserving.
- Avoid import cycles and avoid introducing global state/caches unless the function is clearly pure and you bound cache size.
- Keep async correctness (no blocking I/O, no new concurrency hazards).

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
- IMPORTANT (Windows): this repo contains a `src/nul` file that can make ripgrep error; always exclude it.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'copy\\.deepcopy\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\bjson\\.dumps\\(|\\bmodel_dump\\(|\\bmodel_dump_json\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\bre\\.compile\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\.index\\(|\\.count\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\{\\s*\\*\\*'`

Completion gates (must be satisfied before reporting success)
- Progress tracking: Use a TODO/Task List tool to track: scan -> pick targets -> implement -> run related tests -> commit -> final report.
- Git state (do not block on dirty): Record `git status --porcelain` before editing for context. If it is not empty, continue anyway; do NOT try to "clean" the tree (no stash/reset/checkout), and do NOT stage/commit unrelated changes.
- Branch/remote safety (required): Do NOT create branches, switch branches, detach HEAD, or do any operations on remotes.
  - Confirm you are on a normal branch (not detached): `git rev-parse --abbrev-ref HEAD` must NOT return `HEAD`.
  - Forbidden examples: `git checkout -b`, `git switch -c`, `git checkout <branch>`, `git switch <branch>`, `git pull`, `git push`, `git fetch`, `git remote ...`, `git submodule ...`, `git tag ...`.
- Performance measurement (required):
  - Baseline: run the temporary measurement script twice BEFORE editing any file; record output.
  - Post-change: re-run the same script twice after your change(s); record output and compute the delta.
  - Keep iterating up to 3 attempts if there is no measurable improvement; if still no improvement, revert your code changes for that target.
  - Cleanup: delete the temporary measurement script(s) you created and ensure `git status --porcelain` does not include them (tracked or untracked).
- Tests (required): Identify ALL test files directly related to the files you plan to change, then run them at baseline (pre-change) and again after your changes.
  - Find related tests by searching `tests/` for imports/references to the changed module(s) and key symbols.
  - Baseline (pre-change): run BEFORE editing any file; they must be green. If they fail at baseline, do NOT proceed on this target; pick a different target or STOP and report.
  - Post-change: re-run the same tests after your changes; if any fail, keep fixing and re-run until all pass.
  - Run with: `./.venv/Scripts/python.exe -m pytest <test_file1> <test_file2> ...`
  - Abort protocol: if you cannot get the post-change tests green after 3 fix->test cycles, undo ONLY your session's changes by unstaging/restoring the explicit paths you touched (no globs), then report.
    - If needed: `git restore --staged -- <file>` then `git restore --source=HEAD -- <file>`
- Git safety (required): Do NOT use git operations that can discard/rewrite/hide other agents' work (examples: `git reset --hard`, `git reset`, `git checkout .`, `git restore .`, `git clean -fd`, `git stash`, `git commit --amend`, `git rebase`, `git merge`).
  - If you must undo a broken change or abort the session, only restore files YOU modified, one-by-one with explicit paths: `git restore --source=HEAD -- <file>` (or `git checkout -- <file>`). No globs and never `.`.
- Commit (required only when you keep a performance-improving change): Create exactly ONE commit for this session at the end, after:
  - baseline + post-change related tests are green, AND
  - baseline + post-change measurement shows a clear improvement.
  Commit ONLY the files you changed for this session (never include temporary measurement scripts).
  - Do NOT create multiple commits. Do NOT commit early.
  - Forbidden: `git add .`, `git add -A`, `git add --all`, `git add -u`, `git commit -am`, `git commit -a`, `git stash`.
  - Stage explicitly: `git add <file1> <file2> ...`, then verify: `git diff --cached --name-only`.
  - End state: overall `git status --porcelain` may be non-empty (other agents), but none of the files you touched should remain modified or staged after your commit.

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (file/symbol, old pattern -> new pattern, why it is materially faster/less alloc-heavy).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified (ordering, exceptions, streaming/cancellation).
4) Measurement script details:
   - Path of the temporary script you created (and confirmation it was deleted before finishing).
   - Baseline results (2 runs): iterations, total time, per-iteration time.
   - Post-change results (2 runs): same metrics and the percent delta.
5) Tests you ran (commands + PASS result): include baseline (pre-change) and post-change runs.
6) Commit created (hash + message) and committed files (output of `git show --name-only --pretty=oneline <commit_hash>`), or explicitly state that you reverted changes due to no measurable gain.
7) Post-commit `git status --porcelain` output (may be non-empty if other agents are working); confirm none of the files you touched remain uncommitted and no temporary measurement scripts remain.

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
     - Performance: it ran the temporary measurement script at baseline and post-change, reported the results and delta,
       and confirmed it deleted all temporary measurement scripts before finishing.
       - Optional read-only verification: `git status --porcelain -- dev/scripts/_tmp`
     - Tests: it ran baseline (pre-change) and post-change runs of ALL directly related tests and they passed (commands + PASS result are required).
     - Git: it reported exactly ONE commit hash for its work.
       - Verify the commit exists: `git cat-file -t <commit_hash>` returns `commit`.
       - Verify committed files: `git show --name-only --pretty=oneline <commit_hash>` matches the subagent's reported touched files.
       - Optional sanity check: `git merge-base --is-ancestor <commit_hash> HEAD` succeeds.
   - If the subagent made no changes: do NOT require tests/commit; count this as a "no-fix found" iteration.
5) If (and only if) the subagent changed files and any required gate is missing (baseline tests missing/not green, post-change tests not green, no commit, commit hash missing/mismatch, commit includes extra files): before spawning the follow-up subagent, check whether `./dev/stop_orchestrator_loops.txt` exists; if it does, STOP iterating. If the violation would require forbidden git operations to fix (branch switched/detached, history rewritten, or a bad commit that cannot be corrected without rewriting history), STOP iterating and report. Otherwise spawn a follow-up subagent with brief instructions to fix ONLY that (run/fix tests and/or commit hygiene). Do not fix it yourself.
6) If the subagent failed to find at least one issue to fix in three consecutive iterations: stop iterating (job done).
7) Append newly committed files to the "already fixed files" list before the next iteration (only when a commit was created).
