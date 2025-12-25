Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - resource lifecycle audit (close/cleanup)

Goal
- Improve reliability by ensuring files, network clients, and other resources are consistently cleaned up (closed) in both sync and async code.
- Reduce the risk of file descriptor leaks, socket leaks, and hanging background tasks.

Non-goals (avoid churn)
- Do NOT refactor ownership boundaries (e.g., moving resource creation into DI) unless it is the smallest safe fix.
- Do NOT introduce new dependencies (e.g., do not add `aiofiles`).
- Do NOT change functional behavior (requests made, data returned) beyond ensuring resources are closed.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

What counts as a "resource lifecycle" issue
Prioritize cases that:
1) Open files without context managers:
   - `open(...)` not guarded by `with open(...) as ...:`
2) Create HTTP clients/sessions without closing:
   - `httpx.AsyncClient(...)` not used in `async with ...:` and not `.aclose()`'d in `finally`
   - `httpx.Client(...)` not `.close()`'d
   - `aiohttp.ClientSession(...)` not used in `async with` and not `.close()`'d/`.aclose()`'d
3) Create temp resources without cleanup:
   - `tempfile.TemporaryDirectory()` / `NamedTemporaryFile(...)` without context manager or explicit close
4) Start background tasks without a clear cancellation/cleanup path:
   - `asyncio.create_task(...)` where the task is never cancelled/joined on shutdown (be conservative; fix only clear leaks)

How to pick the best 1-3 refactors (high leverage)
Choose call sites that:
- Are on per-request paths or are used repeatedly.
- Sit on connectors/services that talk to external systems.
- Are likely to leak in long-running proxy processes.
Avoid:
- Short-lived CLI flows unless the leak is severe.
- Resources that are clearly owned and closed elsewhere (e.g., app-wide shared clients closed during shutdown).

Refactor approach (required)
For each selected case:
1) Identify the resource owner and lifetime (function-local vs shared service).
2) Apply the minimal safe fix:
   - Files: use `with open(...) as f:` (or `Path.open()` context manager).
   - Async clients: prefer `async with httpx.AsyncClient(...) as client:` in function-local usage.
   - If function-local `async with` is not feasible, ensure `.aclose()` happens in a `finally` block.
   - Multiple resources: prefer `contextlib.ExitStack` / `contextlib.AsyncExitStack` to keep code readable.
3) Preserve error propagation and cancellation semantics (don’t swallow errors; don’t close shared clients prematurely).
4) Add/update focused unit tests where the leak risk is meaningful (e.g., assert `aclose()` called via a stub).
5) Run targeted tests plus per-file QA (Windows):
   - `./.venv/Scripts/python.exe -m ruff check --fix <changed_file>`
   - `./.venv/Scripts/python.exe -m black <changed_file>`
   - `./.venv/Scripts/python.exe -m mypy <changed_file>`
   - `./.venv/Scripts/python.exe -m pytest <relevant_tests>`

Project constraints
- Keep runtime behavior identical; fix only lifecycle/cleanup.
- Avoid import cycles and avoid introducing global singletons accidentally.
- Follow existing staged initialization patterns when touching app-wide resources.

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\bhttpx\\.AsyncClient\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\baiohttp\\.ClientSession\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\btempfile\\.(TemporaryDirectory|NamedTemporaryFile)\\('`
  - `rg -n -P --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '^\\s*(?!with\\s).*\\bopen\\('`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '\\basyncio\\.create_task\\('`

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (resource, file, old pattern -> new pattern, why it's materially better).
2) List of files changed.
3) Notes on any behavior-sensitive edge cases you verified (shared ownership, shutdown semantics).
4) Tests you ran (commands + result).

Already fixed files (do not modify):
{list-of-fixed-files}
```

Do not execute the above task on your own. That's only subagent's duty, not yours.
After each iteration check subagent status: if it failed to find at least one issue to fix in three consecutive turns - stop iterating. Job is done.
Monitor how well subagents are doing. Look for repeating patterns and field for improvement. If you see prompt template could be improved to increase speed/quality of the subagent's run, please improve it after each turn (when it makes sense).
If it found some issues - please review how it performed. Check if instructions provided to it were clear enough and allowed for fast, high quality and performant task execution. Adjust/improve prompts based on observed subagent performance and behavior.
Keep track of all the files already fixed by subagents in each turn (append after each turn) and pass that list by replacing the `{list-of-fixed-files}` placeholder near the end of the prompt for the subagent and inform it to avoid changing those files as they were already fixed.

