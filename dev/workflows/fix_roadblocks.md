# Project Onboarding & Rules (read first)

- Onboarding docs: `README.md`  
- Rules for agentic coders: `AGENTS.md`  
- Refactor status & goals: `dev/refactoring_status.md`  

This codebase is mid-refactor toward SOLID/DIP. **Assume the migration is incomplete.** If legacy code or legacy tests block progress, **promote the new architecture** (port code/tests) rather than patching legacy modules.

---

## What you must do (strict order)

1. **Run the full test suite once** to collect a complete failure corpus and stack traces. Do not fix anything yet.
2. **Cluster failures into root-cause categories** (e.g., missing DI bindings, interface contract drift, path/IO issues, null/None handling, state leakage, API break, type/shape mismatch, time/tz issues, race/flakiness, import/module resolution, configuration/env, boundary checks, test fragility due to legacy assumptions, etc.). Add more categories if needed.
3. **Prioritize categories by ImpactScore** and produce a **single ordered list** in the format below. Then select **ONE AND ONLY ONE** top category to address now.

---

## How to prioritize (ImpactScore)

For each category, compute:

- **FailCount** = number of failing tests attributable to the category (deduplicate by shared root cause).
- **Breadth** = number of modules/packages touched (proxy for systemic impact).
- **Architecture Alignment** (0–1): how much the fix advances SOLID/DIP migration (prefer solutions that remove legacy coupling).
- **Risk/Complexity** (0–1, inverted): lower risk/complexity → higher score.
- **Reusability** (0–1): likelihood the fix prevents future failures of the same class.
- **ImpactScore** = `0.5*normalize(FailCount) + 0.2*normalize(Breadth) + 0.2*ArchitectureAlignment + 0.1*Reusability - 0.2*RiskComplexity`

Explain any assumptions and normalizations briefly.

---

## Required output (strict format)

Produce **only** this section before doing any code edits:

    PRIORITIZED FAILURE CATEGORIES
    1) <Category name>  | ImpactScore=<float> | Confidence=<low/med/high>
       Root cause (concise): <one-liner>
       Affected dependent code (calling → called):
         - <filepath>:<def_or_class.method>:<line>
         - <filepath>:<def_or_class.method>:<line>
         ...
       Estimated tests fixed if this category is resolved: <integer>
       Evidence/derivation:
         - Tests currently failing due to this category (IDs/patterns): <list or -k patterns>
         - Why they pass after fix: <brief reasoning>
       Proposed fix strategy (architecturally aligned): <1–3 bullets>
       Risks/Mitigations: <bullets>

    2) <Next category> ...

**Notes on “Affected dependent code”:**

- Include **both callers and callees** relevant to the root cause.
- Derive from failure stack traces + static search/AST (e.g., definitions and references). Provide `<filename>:<method>:<line>`. If a symbol is used in multiple places, list the top N most critical by fan-in/fan-out.

---

## Estimating “tests fixed”

Map failing tests to categories via:

- Primary exception types/messages and terminal stack frames.
- Shared origin files/functions in traces.
- Import/DI binding graphs for missing providers/interfaces.

Validate with targeted runs (e.g., `pytest -k "<pattern>"`) when feasible. If you can’t validate, provide a reasoned estimate and mark Confidence accordingly.

---

## Execution policy (after the analysis above)

- Choose **exactly one** category: the highest **ImpactScore** with **med/high Confidence**.
- **Edit plan** (short): list the minimal set of changes to solve the root cause **without** deepening legacy coupling. Prefer: introduce/repair interfaces, inject dependencies, move logic behind ports/adapters, delete legacy shims where safe.
- **Testing workflow (strict)**:
  1) Run only tests **directly touching** the modified file(s); iterate until green.  
  2) Run the **nearest test group/pytest marker**; iterate until green.  
  3) Run the **entire suite**.  
  Re-run the full suite after each subsequent edit batch.

---

## Prohibited / discouraged

- Don’t “fix” legacy modules in place if that entrenches old design; port them into the SOLID/DIP structure instead (and update tests).
- Don’t silence failures by broad try/except, xfail, or skipping, unless explicitly justified and aligned with the new architecture.

---

## Deliverables for this step

1) The **PRIORITIZED FAILURE CATEGORIES** section (as specified).  
2) The chosen **single** category and a **concise edit plan**.  
3) Execute the plan following the testing workflow. Report the delta in failures.

---

## Remember to use `.venv` 

Final notes. When you run Python command and related tools like `pytest`, `mypy`, `ruff`, `bandit`, `vulture` and similar, always remember to prefix commands with proper Python exe name: `.venv/Scripts/python`