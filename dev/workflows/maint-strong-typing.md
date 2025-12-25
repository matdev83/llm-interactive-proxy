Please orchestrate execution of the following task. Create a counter and execute in a loop, up to 50 times. Spawn each task to be executed by a subagent. Spawn only ONE SUBAGENT at time, as this task is not well suited for concurren execution.
Each single task is as follows:

```
Task: Code maintenance — strengthen return types where it matters

Goal
- Improve maintainability, testability, and ease of editing by replacing overly complex / weakly typed function return types with stronger, explicit types.
- Prefer:
  1) Pydantic v2 models (BaseModel / RootModel) for structured data crossing module boundaries, I/O-like shapes, or “record” objects.
  2) dataclasses for simple internal value objects (small, immutable-ish, no validation needs).
  3) Lists/tuples of those models (e.g., list[MyModel]) where appropriate.

Non-goals (avoid churn)
- Do NOT change types just to “replace one type with another” if it doesn’t clearly reduce complexity or improve readability/testing.
- Do NOT refactor public API signatures unless the improvement is meaningful and call sites are updated safely.
- Do NOT touch files listed in “already fixed files”.

Scope and limits
- Scan only ./src/ and its subfolders.
- Use `rg` for all searches.
- Avoid scanning dot/underscore directories (folders starting with `.` or `_`) to skip caches and generated content.
- Fix up to THREE (3) high-impact cases total in this session.

What counts as “overly complex return types”
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
   - -> Union[list[A], list[B], ...] (“union of arrays”)
   - -> Union[list[A], B] (container vs scalar)
4) Tuples that are hard to reason about:
   - -> tuple[Any, ...] or tuple[T, Any] or tuple containing dicts/unions
   - -> tuple[...] where callers use positional magic without names

How to pick the best 1–3 refactors (high leverage)
Choose functions that:
- Have multiple call sites, or sit on important boundaries (service layer, data access, adapters).
- Force callers to do `["key"]` lookups, `isinstance` chains, or shape-checking.
- Are hard to unit test because the returned shape is unclear or brittle.
Avoid:
- One-off helpers with a single local call site unless the current typing actively causes bugs/confusion.

Refactor approach (required)
For each selected function:
1) Identify the return “shape” and name it.
2) Introduce a strong type:
   - Pydantic v2 model(s) for structured records; use field types precisely.
   - dataclass for simple internal records (consider `frozen=True` when sensible).
   - If the function returns a list of records, return `list[Model]` (or `Sequence[Model]` if appropriate).
   - If it returns a single “record or error”, prefer a single model that encodes status, or a well-named sum type pattern (two distinct models) only if it truly clarifies logic.
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
  Example patterns (adapt as needed):
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' '->\s*Any'`
  - `rg -n --glob 'src/**' --glob '!.*/**' --glob '!_*/**' 'dict\[.*Any|Mapping\[.*Any|Union\[|Optional\[Union|list\[dict|tuple\[.*Any'`

Deliverables / reporting (in your final response)
1) Short summary of the up to 3 fixes (function name, file, old return type → new return type, why it’s materially better).
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