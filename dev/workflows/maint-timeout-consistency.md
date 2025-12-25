Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - timeout consistency for outbound I/O

Goal
- Improve reliability by making outbound I/O timeouts explicit and consistent (avoid accidental infinite hangs).
- Prefer using existing timeout configuration/constants already present in the codebase.

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
1) Locate the subsystem’s existing timeout source:
   - A config field, settings object, or module-level constant already used elsewhere.
2) Apply the minimal safe fix:
   - Replace hard-coded literals with the existing timeout constant/config value.
   - If a call has no timeout and the same subsystem already uses a default timeout elsewhere, thread that same timeout into the call.
   - If there is no existing timeout source to reuse safely, DO NOT invent a new number; skip the change and report it as "found but not safely fixable without product decision".
3) Preserve behavior as much as possible:
   - Do not add new timeouts unless you can tie them directly to existing project configuration.
4) Add/update focused unit tests where the timeout value is part of behavior (e.g., ensure it is passed to the client call).
5) Run targeted tests plus per-file QA (Windows):
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
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\btimeout\\s*=\\s*None\\b'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\bhttpx\\.Timeout\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\bhttpx\\.(Client|AsyncClient)\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\brequests\\.(get|post|put|delete|request)\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\b(timeout|connect_timeout|read_timeout|write_timeout)\\s*='`

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (call site, file, old timeout -> new timeout source, why it’s materially better).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified (streaming, retries, exception propagation).
4) Tests you ran (commands + result).
5) Any "found but not safely fixable without product decision" items (file + why).

Already fixed files (do not modify):
{list-of-fixed-files}
```

Do not execute the above task on your own. That's only subagent's duty, not yours.
After each iteration check subagent status: if it failed to find at least one issue to fix in three consecutive turns - stop iterating. Job is done.
Monitor how well subagents are doing. Look for repeating patterns and field for improvement. If you see prompt template could be improved to increase speed/quality of the subagent's run, please improve it after each turn (when it makes sense).
If it found some issues - please review how it performed. Check if instructions provided to it were clear enough and allowed for fast, high quality and performant task execution. Adjust/improve prompts based on observed subagent performance and behavior.
Keep track of all the files already fixed by subagents in each turn (append after each turn) and pass that list by replacing the `{list-of-fixed-files}` placeholder near the end of the prompt for the subagent and inform it to avoid changing those files as they were already fixed.

