Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurren execution.
Each single task is as follows:

```
Task: Code maintenance — strengthen return types where it matters

Goal
- Improve maintainability, testability, and ease of editing by replacing overly complex / weakly typed function return types with stronger, explicit types.
- Prefer:
  1) Pydantic v2 models (BaseModel / RootModel) for structured data crossing module boundaries, I/O-like shapes, or "record" objects.
  2) dataclasses for simple internal value objects (small, immutable-ish, no validation needs).
  3) Lists/tuples of those models (e.g., list[MyModel]) where appropriate.

Non-goals (avoid churn)
- Do NOT change types just to "replace one type with another" if it doesn't clearly reduce complexity or improve readability/testing.
- Do NOT refactor public API signatures unless the improvement is meaningful and call sites are updated safely.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

What counts as overly complex return types
Prioritize functions returning any of the following (examples use Python typing syntax):
1) Any or implicit Any:
   - -> Any
   - -> dict / list / tuple without type params
   - -> dict[str, Any] / Mapping[str, Any]
2) Complex dict shapes:
   - -> dict[str, object] with mixed/alternating value types
   - -> dict[str, Union[A, B, ...]] or deeply nested dict/list combos
   - -> list[dict[str, Any]] or dict[str, list[dict[str, Any]]]
3) Union-heavy or container+union combos:
   - -> Union[A, B, C] where callers branch on shape/type
   - -> Optional[Union[A, B, ...]] (same problem, extra None case)
   - -> list[Union[A, B]] / Sequence[Union[A, B]]
   - -> Union[list[A], list[B], ...] ("union of arrays")
   - -> Union[list[A], B] (container vs scalar)
4) Tuples that are hard to reason about:
   - -> tuple[Any, ...] or tuple[T, Any] or tuple containing dicts/unions
   - -> tuple[...] where callers use positional magic without names

How to pick the best 1-3 refactors (high leverage)
Choose functions that:
- Have multiple call sites, or sit on important boundaries (service layer, data access, adapters).
- Force callers to do `["key"]` lookups, `isinstance` chains, or shape-checking.
- Are hard to unit test because the returned shape is unclear or brittle.
Avoid:
- One-off helpers with a single local call site unless the current typing actively causes bugs/confusion.

Refactor approach (required)
For each selected function:
1) Identify the return "shape" and name it.
2) Introduce a strong type:
   - Pydantic v2 model(s) for structured records; use field types precisely.
   - dataclass for simple internal records (consider `frozen=True` when sensible).
   - If the function returns a list of records, return `list[Model]` (or `Sequence[Model]` if appropriate).
   - If it returns a single "record or error", prefer a single model that encodes status, or a well-named sum type pattern (two distinct models) only if it truly clarifies logic.
3) Update the function signature and implementation to return the new type(s).
4) Refactor ALL call sites and dependent code (including tests) to use the new typed interface.
5) Add/adjust focused tests where the change improves confidence:
   - Prefer small unit tests over integration tests.
   - Only run tests directly related to changed files / modules (do NOT run the full suite).

Project constraints
- Use codebase standards and existing conventions for model placement/naming.
- Avoid import cycles. If needed, place models in a dedicated `types.py`/`models.py` near the feature area.
- Keep runtime behavior identical unless there is a clear bug fix aligned with the typing refactor.

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
- IMPORTANT (Windows): this repo contains a `src/nul` file that can make ripgrep error; always exclude it.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' '->\s*Any'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' --glob '!src/nul' --glob '!**/nul' 'dict\[.*Any|Mapping\[.*Any|Union\[|Optional\[Union|list\[dict|tuple\[.*Any'`

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
1) Short summary of the up to 3 fixes (function name, file, old return type -> new return type, why it's materially better).
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
