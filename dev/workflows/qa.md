# Project-wide QA Quality Gate (Ruff → Black → Ruff → Mypy)

## Onboarding & Scope
- Read: `README.md`, `AGENTS.md`, `CHANGELOG.md`
- **Do not propose or apply changes in:** `app_config.py`, `application_factory.py`, `conftest.py`
- Operate only on project sources and tests.
- **Always** run tools via the project venv:
  - Prefix commands with: `.venv/Scripts/python -m <tool>`

---

## Environment & Conventions

- Detect tests directory: if both `test/` and `tests/` exist, treat both as test roots.
- Never modify tool configs unless explicitly instructed (respect `pyproject.toml`, `ruff.toml`, `mypy.ini`, etc.).
- Idempotence is required: keep looping until **Ruff and Black make zero changes** before starting Mypy.

---

## Execution Plan (strict)

1) **Record tool versions (for audit)**
   ~~~bash
   .venv/Scripts/python -m ruff --version
   .venv/Scripts/python -m black --version
   .venv/Scripts/python -m mypy --version
   ~~~

2) **Ruff pass #1 (autofix)**
   - Targets: `src/` and test roots (`test/` and/or `tests/`)
   ~~~bash
   .venv/Scripts/python -m ruff check src test tests --fix
   ~~~
   - If Ruff reports “autofix disabled/unavailable” violations, capture them for **manual single-file fixes**.

3) **Manual fixes for non-autofixable Ruff issues**
   - Apply **small, localized** edits only.
   - Do **not** touch ignored files.

4) **Black (format)**
   ~~~bash
   .venv/Scripts/python -m black src test tests
   ~~~

5) **Ruff pass #2 (post-Black)**
   - If Black made any changes, run Ruff again:
   ~~~bash
   .venv/Scripts/python -m ruff check src test tests --fix
   ~~~

6) **Stabilize (idempotence loop)**
   - Repeat steps 4→5 until **both**:
     - Black prints “All done! ✨ 🍰 ✨” with `0 files reformatted, 0 files left unchanged` deltas
     - Ruff prints no further fixes and no new violations (aside from acknowledged manual-fix items)

7) **Mypy (type check)**
   ~~~bash
   .venv/Scripts/python -m mypy src tests
   ~~~
   - Prioritize fixes in this order:
     1. **Correctness-critical**: `attr-defined`, `arg-type`, `call-arg`, `return-value`, `assignment`, `index`, `operator`
     2. **Interface drift**: `override`, `abstract`, `no-redef`, `name-defined`
     3. **Typing hygiene**: `union-attr`, `misc`, `unused-ignore`, narrowing/None-guards
   - Prefer local type annotations, precise `TypedDict`/`Protocol`, and narrow `Optional` guards over `Any`.

> Only proceed to Mypy **after** Ruff/Black are stable (no changes). If Mypy suggests edits that would trigger new Ruff/Black changes, re-run the loop.

---

## Categorization & Severity (for reporting and prioritization)

Order findings by severity (highest first):

1. **S1 – Type-correctness risk (Mypy critical)**  
   - `attr-defined`, `arg-type`, `return-value`, `call-arg`, `assignment`, `index`, `operator`
2. **S2 – Ruff correctness/bug-prone**  
   - `F*` (pyflakes), `B*` (bugbear), `E9*` (syntax/logic), `PIE*`, `DTZ*`, `PERF*`
3. **S3 – Import/order/config hygiene**  
   - `I*` (isort), `TID*`, `PLC/PLE` (pylint codes surfaced via Ruff)
4. **S4 – Style & consistency**  
   - `E/W` style, docstrings, formatting drift (fixed by Black)
5. **S5 – Low-impact & nits**  
   - Minor readability, comments, naming that do not affect behavior

> Within each category, **cluster by rule code** and **module/package**, then sort by **Failing count → Fan-in of impacted code → Edit locality**.

---

## Required Output (produce before and after the QA cycle)

### A. **QA QUALITY GATE – PRE RUN**
~~~
INPUTS
- Source roots: src/
- Test roots: <test|tests> (detected: <list>)
- Ignored files: app_config.py, application_factory.py, conftest.py
- Tool versions: Ruff=<ver>, Black=<ver>, Mypy=<ver>

PLAN
- Ruff → Black → Ruff until idempotent
- Then Mypy
~~~

### B. **QA FINDINGS (ordered by severity)**
For each **Category** (S1→S5):
- **Category**: <name> (e.g., “S1/Mypy: attr-defined”)
- **Count**: <violations> | **Files**: <unique-files>  
- **Top locations (calling → called)**:
  - `<file>:<def_or_class.method>:<line>` → `<callee_file>:<def>:<line>` (if applicable)
  - …
- **Representative violation(s)**: `<rule or error code>` with short message(s)
- **Fix intent (≤3 bullets)**:
  - <concise local change>
- **Expected side-effects**: <none/low/med/high>

### C. **QA ACTIONS (idempotence loop)**
- **Ruff #1 changes**: <n files, n fixes> | outstanding manual items: <n>
- **Black changes**: <n files reformatted>
- **Ruff #2 changes**: <n files, n fixes>
- **Idempotent?** <yes/no> (if no, repeat summary until yes)

### D. **MYPY RESULTS**
- **Errors by code** (top 10): table of `code | count | top files`
- **Fixed in this pass**: <count> | **Remaining**: <count>
- **Blockers** (if any): <list> (do not touch ignored files)

### E. **POST RUN STATUS**
- **Ruff**: clean (no fixes, no violations needing edits)
- **Black**: clean (no changes)
- **Mypy**: <0 errors | N errors remaining>
- **Residual risk**: <low/med/high> with brief justification
- **Next steps**: <bullets> (if anything remains)

---

## Command Canon (always via `.venv`)

~~~bash
# Ruff (autofix on both src and tests if present)
.venv/Scripts/python -m ruff check src test tests --fix

# Black (format sources and tests)
.venv/Scripts/python -m black src test tests

# Repeat Ruff after Black
.venv/Scripts/python -m ruff check src test tests --fix

# Mypy (type checking)
.venv/Scripts/python -m mypy src tests

# (Optional) Security and dead code scans—prefix with .venv as well
.venv/Scripts/python -m bandit -q -r src
.venv/Scripts/python -m vulture src tests
~~~

> If a directory (`test/` or `tests/`) does not exist, the tool will ignore it; do not fail the pipeline solely for its absence.

---

## Guardrails

- Do **not** modify `app_config.py`, `application_factory.py`, or `conftest.py` under any circumstance in this QA pass.
- Keep edits **local and minimal**; avoid cross-module refactors.
- If a fix would cascade into architectural changes, **stop** and report it under **Blockers**.

---

## Completion Criteria (Quality Gate)

- **Pass** when:
  - Ruff & Black are **idempotent** (no changes on rerun)
  - Mypy is **error-free** (or remaining errors are explicitly documented as Blockers outside QA scope)
- Provide the full **QA QUALITY GATE** report sections A→E.