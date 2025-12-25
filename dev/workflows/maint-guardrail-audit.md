Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - guardrail audit for unsafe patterns

Goal
- Reduce security and safety risk by removing or hardening clearly unsafe coding patterns.
- Prefer fixes that are low-risk and do not require product decisions (no new features).

Non-goals (avoid churn)
- Do NOT introduce new functionality or new configuration knobs.
- Do NOT make behavior-breaking validation changes unless the current behavior is clearly unsafe (e.g., path traversal, command injection, unsafe deserialization).
- Do NOT add new dependencies.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

What counts as "unsafe patterns"
Prioritize issues that are unambiguously risky in a proxy that handles untrusted inputs:
1) Unsafe command execution primitives:
   - `subprocess.*(..., shell=True)` or string-form command building with untrusted inputs
2) Unsafe deserialization:
   - `pickle.load(s)` on data that could be untrusted
   - `yaml.load(...)` without a safe loader where untrusted YAML is possible
3) Path traversal risks:
   - constructing filesystem paths from request/user input without normalization and boundary checks
4) Secret leakage:
   - logging raw headers, authorization tokens, API keys, or request bodies containing secrets

How to pick the best 1-3 refactors (high leverage)
Choose code that:
- Is reachable from HTTP endpoints, WebSocket endpoints, or "tool" execution paths.
- Operates on user-controlled strings, paths, headers, or payloads.
- Has high blast radius (used by multiple subsystems).
Avoid:
- Code that is clearly internal-only, test-only, or already guarded by strong sandbox/allowlist logic (unless the guard is broken).

Refactor approach (required)
For each selected case:
1) Prove the risk:
   - Identify what input can be user-controlled and how it reaches the unsafe primitive.
2) Apply the smallest safe fix that preserves behavior:
   - Commands: prefer list-form args, `shell=False`, strict allowlists, and explicit validation when user input participates.
   - YAML: prefer `safe_load` if (and only if) the YAML content does not require unsafe tags; otherwise do not change without a clear compatibility check.
   - Paths: normalize (`resolve()`), then enforce "must be within allowed root" using existing sandbox/policy helpers if present.
   - Secrets: redact before logging; prefer central helper if one exists in the repo.
3) Preserve error semantics and logging standards (use `exc_info=True` for unexpected errors; do not swallow).
4) Add or update focused unit tests that demonstrate the guardrail works (e.g., path traversal rejected; secrets redacted; shell=True removed).
5) Run targeted tests plus per-file QA (Windows):
   - `./.venv/Scripts/python.exe -m ruff check --fix <changed_file>`
   - `./.venv/Scripts/python.exe -m black <changed_file>`
   - `./.venv/Scripts/python.exe -m mypy <changed_file>`
   - `./.venv/Scripts/python.exe -m pytest <relevant_tests>`

Project constraints
- Avoid making broad "security rewrites" in one go; keep changes localized and reviewable.
- Avoid import cycles; place shared helpers in existing utility modules when appropriate.
- Keep runtime behavior identical unless the current behavior is clearly unsafe.

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
- IMPORTANT (Windows): this repo contains a `src/nul` file that can make ripgrep error; always exclude it.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'shell\\s*=\\s*True|subprocess\\.'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\bpickle\\.(load|loads)\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '\\byaml\\.load\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '(Authorization|api[_-]?key|secret|token)\\b'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '(Path\\(|os\\.path\\.join\\(|pathlib)\\b'`

Completion gates (must be satisfied before reporting success)
- Progress tracking: Use a TODO/Task List tool to track: scan -> pick targets -> implement -> run related tests -> commit -> final report.
- Start clean: Run `git status --porcelain` before editing. If it is not empty, STOP and report back (do not stash/reset/checkout the whole tree).
- Branch/remote safety (required): Do NOT create branches, switch branches, detach HEAD, or do any operations on remotes.
  - Confirm you are on a normal branch (not detached): `git rev-parse --abbrev-ref HEAD` must NOT return `HEAD`.
  - Forbidden examples: `git checkout -b`, `git switch -c`, `git checkout <branch>`, `git switch <branch>`, `git pull`, `git push`, `git fetch`, `git remote ...`, `git submodule ...`, `git tag ...`.
- Tests (required): Identify ALL test files directly related to the files you plan to change, then run them at baseline (pre-change) and again after your changes.
  - Find related tests by searching `tests/` for imports/references to the changed module(s) and key symbols.
  - Baseline (pre-change): run BEFORE editing any file; they must be green. If they fail at baseline, do NOT proceed on this target; pick a different target or STOP and report.
  - Post-change: re-run the same tests after your changes; if any fail, keep fixing and re-run until all pass.
  - Run with: `./.venv/Scripts/python.exe -m pytest <test_file1> <test_file2> ...`
  - Abort protocol: if you cannot get the post-change tests green after 3 fix->test cycles, restore only the files you changed (explicit paths, no globs) until `git status --porcelain` is clean, then report.
- Git safety (required): Do NOT use git operations that can discard/rewrite/hide other agents' work (examples: `git reset --hard`, `git reset`, `git checkout .`, `git restore .`, `git clean -fd`, `git stash`, `git commit --amend`, `git rebase`, `git merge`).
  - If you must undo a broken change or abort the session, only restore files YOU modified, one-by-one with explicit paths: `git restore --source=HEAD -- <file>` (or `git checkout -- <file>`). No globs and never `.`.
- Commit (required if you changed any files): Create exactly ONE commit for this session at the end, after baseline + post-change related tests are green; commit ONLY the files you changed for this session.
  - Do NOT create multiple commits. Do NOT commit early.
  - Forbidden: `git add .`, `git add -A`, `git add --all`, `git add -u`, `git commit -am`, `git commit -a`, `git stash`.
  - Stage explicitly: `git add <file1> <file2> ...`, then verify: `git diff --cached --name-only`.
  - End state must be clean: `git status --porcelain` is empty.

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (risk, file, old pattern -> new pattern, why it's materially safer).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified.
4) Tests you ran (commands + PASS result): include baseline (pre-change) and post-change runs.
5) Commit created (hash + message) and committed files (output of `git show --name-only --pretty=oneline <commit_hash>`).
6) Post-commit `git status --porcelain` output (should be empty).

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
