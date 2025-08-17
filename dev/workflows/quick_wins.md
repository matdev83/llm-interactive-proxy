# Quick-Wins First Aid (single-file fixes only)

## Onboarding & Rules
- Read: `README.md`, `AGENTS.md`, `CHANGELOG.md`
- **Ignore entirely:** `app_config.py`, `application_factory.py`, `conftest.py` (do not propose or apply changes in these files)
- Goal: Identify and fix **exactly one** “easy win” that restores tests with a **single-file**, **low-risk** change. No multi-file refactors.

---

## What counts as an “Easy Win”
Prefer issues resolvable by editing a **single file** with a **small patch** (e.g., ≤ 25 changed LOC) such as:
- Missed/wrong import, wrong symbol/attribute name, obvious typos
- Incorrect default arg / parameter order / None-guard / off-by-one
- Simple path/IO/encoding fix, trivial regex/format bug
- Trivial mock/fixture usage inside a **test file** (but not `conftest.py`)
- Straightforward return value/contract adjustment that does **not** break public API
- Deterministic flake due to local state (reset/clear within the same file)

**Not allowed:** cross-file interface changes, moving classes/functions between modules, API redesigns, dependency graph edits, DB migrations, DI/container edits, changes to the ignored files above.

---

## Process (strict)

1) **Collect failures:** Run the full test suite once to capture failure corpus & stack traces. Do not edit yet.  
2) **Filter candidates:** From failures, shortlist only those whose **terminal stack frames and required edits are in one file** (excluding ignored files).  
3) **Score & prioritize** with **QuickWinScore** (formula below).  
4) **Output the shortlist (top 3)** in the required format.  
5) **Pick ONE** highest-scoring item (with med/high Confidence).  
6) **Fix** using the testing workflow below, then report delta.

---

## Scoring: QuickWinScore (prioritize fixability over impact)

For each candidate failure `i`, compute:

- **Locality** (0–1): all implicated frames/edits in one file (1 if yes, else 0; required ≥ 0.8)
- **ChangeSize** (estimated changed LOC; lower is better)
- **Risk** (0–1): likelihood of side effects (lower is better)
- **TimeToGreen** (qualitative 1–5; smaller is better)
- **TestsFixed** (integer): how many tests become green if fixed

**Normalize** `ChangeSize`, `TimeToGreen`, and `TestsFixed` to [0,1].  
**QuickWinScore =**  
`0.35*Locality + 0.25*(1 - norm(ChangeSize)) + 0.20*(1 - Risk) + 0.20*norm(TestsFixed) - 0.10*norm(TimeToGreen)`

> Constraints: require `Locality ≥ 0.8` and `Risk ≤ 0.5`. Briefly explain any assumptions/normalizations.

---

## Required output (before any code edits)

Produce **only** the section below first:

---

## Remember to use `.venv` 

Final notes. When you run Python command and related tools like `pytest`, `mypy`, `ruff`, `bandit`, `vulture` and similar, always remember to prefix commands with proper Python exe name: `.venv/Scripts/python`