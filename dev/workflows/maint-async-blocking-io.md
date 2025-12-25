Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - async blocking I/O audit

Goal
- Reduce event-loop blocking in async code paths by replacing obvious blocking I/O / blocking waits inside `async def` with non-blocking equivalents.
- Preserve behavior while improving responsiveness under load (no new features).

Non-goals (avoid churn)
- Do NOT rewrite whole modules to async or change public APIs unless strictly required to remove blocking.
- Do NOT add new dependencies.
- Do NOT change business logic, retries, routing, or error surfaces.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

What counts as "blocking I/O / waits" in async code
Prioritize cases where an `async def` (or code reachable from request handlers) does any of:
1) Blocking sleeps:
   - `time.sleep(...)`
2) Blocking subprocess calls:
   - `subprocess.run(...)`, `subprocess.check_output(...)`, `subprocess.Popen(...).communicate()`
3) Synchronous HTTP calls in async code:
   - `requests.get/post/request(...)` (or any sync client) called inside `async def`
4) Potentially heavy sync filesystem operations in async code:
   - `open(...).read()/write()`, `Path.read_text/read_bytes/write_text/write_bytes`

How to pick the best 1-3 refactors (high leverage)
Choose call sites that:
- Are on hot paths (request handling, connectors, routing, capture, accounting).
- Are likely executed per-request or per-stream chunk.
- Have multiple call sites or are reused utilities.
Avoid:
- CLI-only code, one-off scripts, or initialization-only code unless it blocks startup noticeably.

Refactor approach (required)
For each selected case:
1) Confirm it is executed in an async context (`async def` call chain).
2) Replace with the safest non-blocking equivalent:
   - `time.sleep(x)` -> `await asyncio.sleep(x)`
   - For sync I/O with no existing async equivalent in the codebase, offload using `await asyncio.to_thread(...)` (or `anyio.to_thread.run_sync` if already used in that area).
   - Prefer existing async HTTP client patterns in the repo (e.g., `httpx.AsyncClient`) if already present in that subsystem; otherwise offload the sync call to a thread rather than introducing new dependencies.
3) Preserve exception and cancellation semantics:
   - Do not swallow exceptions.
   - Do not accidentally convert `CancelledError` into a generic failure.
4) Update tests or add focused unit tests for the changed function(s).
5) Run targeted tests plus per-file QA (Windows):
   - `./.venv/Scripts/python.exe -m ruff check --fix <changed_file>`
   - `./.venv/Scripts/python.exe -m black <changed_file>`
   - `./.venv/Scripts/python.exe -m mypy <changed_file>`
   - `./.venv/Scripts/python.exe -m pytest <relevant_tests>`

Project constraints
- Keep runtime behavior identical aside from removing event-loop blocking.
- Avoid import cycles and large refactors.
- Use existing logging and error conventions.

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\btime\\.sleep\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\bsubprocess\\.(run|check_output|Popen)\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\brequests\\.(get|post|put|delete|request)\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\bPath\\([^)]*\\)\\.(read_text|read_bytes|write_text|write_bytes)\\('`

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (function name, file, old pattern -> new pattern, why it's materially better).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified (cancellation, exception propagation).
4) Tests you ran (commands + result).

Already fixed files (do not modify):
{list-of-fixed-files}
```

Do not execute the above task on your own. That's only subagent's duty, not yours.
After each iteration check subagent status: if it failed to find at least one issue to fix in three consecutive turns - stop iterating. Job is done.
Monitor how well subagents are doing. Look for repeating patterns and field for improvement. If you see prompt template could be improved to increase speed/quality of the subagent's run, please improve it after each turn (when it makes sense).
If it found some issues - please review how it performed. Check if instructions provided to it were clear enough and allowed for fast, high quality and performant task execution. Adjust/improve prompts based on observed subagent performance and behavior.
Keep track of all the files already fixed by subagents in each turn (append after each turn) and pass that list by replacing the `{list-of-fixed-files}` placeholder near the end of the prompt for the subagent and inform it to avoid changing those files as they were already fixed.

