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
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' 'shell\\s*=\\s*True|subprocess\\.'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\bpickle\\.(load|loads)\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\byaml\\.load\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '(Authorization|api[_-]?key|secret|token)\\b'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '(Path\\(|os\\.path\\.join\\(|pathlib)\\b'`

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (risk, file, old pattern -> new pattern, why it’s materially safer).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified.
4) Tests you ran (commands + result).

Already fixed files (do not modify):
{list-of-fixed-files}
```

Do not execute the above task on your own. That's only subagent's duty, not yours.
After each iteration check subagent status: if it failed to find at least one issue to fix in three consecutive turns - stop iterating. Job is done.
Monitor how well subagents are doing. Look for repeating patterns and field for improvement. If you see prompt template could be improved to increase speed/quality of the subagent's run, please improve it after each turn (when it makes sense).
If it found some issues - please review how it performed. Check if instructions provided to it were clear enough and allowed for fast, high quality and performant task execution. Adjust/improve prompts based on observed subagent performance and behavior.
Keep track of all the files already fixed by subagents in each turn (append after each turn) and pass that list by replacing the `{list-of-fixed-files}` placeholder near the end of the prompt for the subagent and inform it to avoid changing those files as they were already fixed.

