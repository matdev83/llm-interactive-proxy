Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurren execution. Use this type of agent: `glm`.
Each single task is as follows:

```
Task: Code maintenance — strengthen return types where it matters

Goal
- Improve maintainability, testability, and ease of editing by replacing overly complex / weakly typed function return types with stronger, explicit types.
- Prefer:
  1) Pydantic v2 models (BaseModel / RootModel) for structured data crossing module boundaries, I/O-like shapes, or "record" objects.
  2) dataclasses for simple internal value objects (small, immutable-ish, no validation needs).
  3) Lists/tuples of those models (e.g., list[MyModel]) where appropriate.
- IMPORTANT: A typing refactor is not "done" until ALL dependent call sites/receivers and ALL directly related tests are updated to the new contract.

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
4) Build an "impact map" BEFORE changing the signature (required):
   - Enumerate call sites (including tests) with `rg` and record the results you must update (file:line + call expression).
   - Enumerate receivers and shape assumptions (examples: `["key"]` lookups, tuple unpacking, `isinstance` branching, `len(...)` assumptions, `None` checks).
   - Identify ALL directly related tests that import/call the function or its module, and plan to run them at baseline.
5) Refactor ALL call sites and dependent code (including tests) to use the new typed interface (required):
   - Update call sites AND any intermediate wrapper functions that forward/transform the return value.
   - Update callers to avoid recreating the old weak shape (no converting the new model back into `dict[str, Any]` to "make existing code work").
   - Update typing at boundaries (protocols/interfaces, adapters, mocks, fixtures) so mypy and tests agree on the new contract.
6) Add/adjust focused tests where the change improves confidence and prevents regressions:
   - Prefer small unit tests over integration tests.
   - Only run tests directly related to changed files / modules (do NOT run the full suite).
   - If you changed a return type used by multiple call sites, add/adjust tests so each call site path is exercised at least once (or explain why a call site is unreachable in tests).
7) Contract-change completeness check (required, after code changes):
   - Re-run `rg` to confirm you updated all previously recorded call sites.
   - Add a follow-up `rg` for the old access patterns you removed (examples: old keys, old tuple unpacking, old type name) and confirm there are no remaining hits.
8) After each file edit you will be provided with LSP server diagnostic/linting output. Fix all of such issues reported even if you think they are not related to your changes.

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
- Contract-change completeness (required): For each changed return type, show the "impact map" you created (call sites/receivers/tests) and confirm every item was updated.
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
1) Short summary of the up to 3 fixes (function name, file, old return type -> new return type, why it's materially better).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified.
4) Impact map (required): call sites/receivers/tests you identified BEFORE changing the return type (include the `rg` commands you used and a short list of results).
5) Contract verification (required): the follow-up `rg` checks you ran to prove no call sites/old patterns remain.
6) Tests you ran (commands + PASS result): include baseline (pre-change) and post-change runs.
7) Commit created (hash + message) and committed files (output of `git show --name-only --pretty=oneline <commit_hash>`).
8) Post-commit `git status --porcelain` output (may be non-empty if other agents are working); confirm none of the files you touched remain uncommitted.

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
