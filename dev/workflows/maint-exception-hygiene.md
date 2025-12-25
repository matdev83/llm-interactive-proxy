Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurrent execution.
Each single task is as follows:

```
Task: Code maintenance - exception hygiene and logging

Goal
- Improve maintainability and debuggability by replacing overly broad exception handling with precise exceptions and consistent logging.
- Ensure exception handling follows project standards (LLMProxyError hierarchy, async correctness, logging with exc_info=True).

Non-goals (avoid churn)
- Do NOT change runtime behavior or error surfaces unless the current behavior is clearly unsafe (e.g., bare except swallowing errors silently).
- Do NOT refactor large control flow just to "clean up" exceptions.
- Do NOT touch files listed in "already fixed files".

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

What counts as "exception hygiene" issues
Prioritize cases that:
1) Use bare or too-broad handlers:
   - `except:`
   - `except Exception:`
   - `except BaseException:`
2) Swallow exceptions with no logging or context:
   - `except ...: pass`
   - `except ...: return None` or default value without logging
3) Log without stack trace:
   - `logger.error("...", exc_info=False)` or missing `exc_info=True` for unexpected errors
4) Catch/raise patterns that hide root causes:
   - `raise SomeError("...")` without chaining or context when rethrowing a lower-level exception

How to pick the best 1-3 refactors (high leverage)
Choose handlers that:
- Sit on boundaries (connectors, service layer, controllers).
- Affect multiple call sites or error reporting paths.
- Make debugging painful due to lost context.
Avoid:
- One-off helpers with a single local call site unless the current handling is actively dangerous.

Refactor approach (required)
For each selected handler:
1) Identify the expected exception types and use the most precise type(s) available.
2) Preserve behavior:
   - If a handler must swallow an error, add logging with context and `exc_info=True`.
   - If rethrowing, use exception chaining (`raise ... from err`) where appropriate.
3) Keep async correctness (no blocking I/O in handlers).
4) Update tests and call sites to reflect the stronger error semantics when needed.
5) Add focused unit tests if behavior is subtle or error handling is important.

Project constraints
- Use codebase standards and existing conventions.
- Prefer `LLMProxyError` and existing exception classes where appropriate.
- Avoid import cycles.
- Keep runtime behavior identical unless there is a clear bug fix aligned with the hygiene improvements.

Search rules (must follow)
- Use `rg` for searches. Limit to ./src/.
- Exclude directories starting with `.` or `_`.
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' 'except\\s*:'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' 'except\\s+Exception|except\\s+BaseException'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' 'exc_info\\s*=\\s*False|logger\\.error\\('`

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (function name, file, old handler -> new handler, why it's materially better).
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
