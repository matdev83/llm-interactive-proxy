#!/usr/bin/env python3
"""
Exception Hygiene Fix Orchestrator

This script orchestrates fixes for exception hygiene issues detected by the linter.
It runs the linter, groups findings, and spawns zenglm subagents to fix them in batches.

Usage:
    python dev/scripts/orchestrate_exception_hygiene_fixes.py

The orchestrator is READ ONLY - it only spawns subagents, makes no direct file edits.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def run_linter() -> list[dict[str, Any]]:
    """Run the exception hygiene linter and return all findings."""
    print("=" * 80)
    print("RUNNING EXCEPTION HYGIENE LINTER")
    print("=" * 80)

    result = subprocess.run(
        ["./.venv/Scripts/python.exe", "dev/scripts/run_exception_hygiene_linter.py"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )

    # Print the output
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr, file=sys.stderr)

    # Read the JSON output
    findings_file = (
        project_root / "dev" / "artifacts" / "exception_hygiene_findings.json"
    )
    if not findings_file.exists():
        print(f"ERROR: Findings file not found: {findings_file}")
        return []

    findings = json.loads(findings_file.read_text(encoding="utf-8"))
    return findings


def group_findings_into_batches(
    findings: list[dict[str, Any]], batch_size: int = 3
) -> list[list[dict[str, Any]]]:
    """
    Group findings into batches for processing.

    Strategy:
    1. Prioritize EXH004 (critical bugs) first
    2. Then EXH001 (missing exc_info)
    3. Finally EXH003 (silent handlers)
    4. Group by file to minimize context switching
    """
    # Sort by priority: EXH004 > EXH001 > EXH003, then by file
    priority_order = {"EXH004": 0, "EXH001": 1, "EXH003": 2}
    findings.sort(
        key=lambda f: (priority_order.get(f["code"], 999), f["filename"], f["lineno"])
    )

    # Group into batches
    batches = []
    current_batch = []

    for finding in findings:
        current_batch.append(finding)

        if len(current_batch) >= batch_size:
            batches.append(current_batch)
            current_batch = []

    # Add remaining findings
    if current_batch:
        batches.append(current_batch)

    return batches


def create_fix_task_prompt(
    batch: list[dict[str, Any]], iteration: int, total_batches: int
) -> str:
    """Create a detailed task prompt for the zenglm subagent."""

    # Group findings by file for better presentation
    by_file = {}
    for finding in batch:
        filename = finding["filename"]
        if filename not in by_file:
            by_file[filename] = []
        by_file[filename].append(finding)

    # Build the prompt
    prompt = f"""# Exception Hygiene Fix Task - Iteration {iteration}/{total_batches}

You are tasked with fixing {len(batch)} exception hygiene issues detected by our linter.

## Your Responsibilities

1. **Read the affected files** to understand the context
2. **Fix each issue** according to the rules below
3. **Run tests** to ensure no regressions
4. **Commit the changes** with a descriptive message

## Issues to Fix

"""

    for filename, file_findings in by_file.items():
        prompt += f"\n### File: `{filename}`\n\n"
        for finding in file_findings:
            prompt += f"- **Line {finding['lineno']}** - {finding['code']}: {finding['message']}\n"

    prompt += """

## Fix Guidelines

### EXH001: Missing exc_info=True

**Problem:** Logger calls in exception handlers are missing `exc_info=True`, losing stack trace information.

**Fix:**
```python
# BEFORE
except SomeException as e:
    logger.error("Operation failed")
    
# AFTER
except SomeException as e:
    logger.error("Operation failed", exc_info=True)
```

**Note:** If the logger call is `logger.exception()`, it already includes exc_info implicitly - no change needed.

### EXH003: Silent Exception Handler

**Problem:** Exception handlers with just `pass` and no logging make debugging impossible.

**Fix:** Add appropriate logging:
```python
# BEFORE
except SomeException:
    pass
    
# AFTER (if this is truly expected and should be silent)
except SomeException:
    # Intentionally ignoring error - this is expected in cleanup
    pass
    
# AFTER (if this might indicate a problem)
except SomeException as e:
    logger.warning("Unexpected error during cleanup", exc_info=True)
```

**Judgment required:** You need to determine if the silent handler is:
1. Intentional (cleanup, optional operations) - add comment explaining why
2. Potentially masking bugs - add logging

### EXH004: Incorrect exc_info Usage

**Problem:** Using `exc_info=variable` instead of `exc_info=True`

**Fix:**
```python
# BEFORE
except SomeException as e:
    logger.error("Failed", exc_info=e)  # WRONG - doesn't work
    
# AFTER
except SomeException as e:
    logger.error("Failed", exc_info=True)  # CORRECT
```

## Testing Requirements

**Before making changes:**
1. Identify which test files cover the code you're modifying
2. Run those tests to establish baseline: `pytest <test_file> -v`

**After making changes:**
1. Run the same tests again to verify no regressions
2. If tests fail, fix the issue or revert your changes
3. Only commit if all tests pass

**Test discovery:**
- For `src/connectors/foo.py`, look for `tests/unit/test_foo.py` or `tests/integration/test_foo*.py`
- For `src/core/services/bar.py`, look for `tests/unit/test_bar.py`
- If you can't find specific tests, run: `pytest tests/unit -v -k "keyword"` where keyword relates to the module

## Commit Requirements

**Create exactly ONE commit** for this batch of fixes.

**Commit message format:**
```
fix(exception-hygiene): Fix {count} issues in {file_count} files (iteration {iteration})

- EXH001: {count_exh001} missing exc_info=True
- EXH003: {count_exh003} silent handlers  
- EXH004: {count_exh004} incorrect exc_info usage

Affected files:
- {filename1}
- {filename2}
...
```

**Example:**
```
fix(exception-hygiene): Fix 3 issues in 2 files (iteration 1)

- EXH001: 2 missing exc_info=True
- EXH003: 1 silent handler

Affected files:
- src/connectors/openai.py
- src/core/services/rate_limiter.py
```

## Important Constraints

1. **NO cosmetic changes** - only fix the specific issues listed
2. **NO refactoring** - keep the surrounding code as-is
3. **NO formatting changes** - ruff/black will handle that in CI
4. **Test must pass** - if tests fail, you must fix or revert
5. **One commit only** - don't create multiple commits

## Success Criteria

- ✅ All {len(batch)} issues are fixed correctly
- ✅ All relevant tests pass
- ✅ Exactly one commit is created
- ✅ Commit message follows the format above

## Workflow Summary

1. Read all affected files to understand context
2. Make fixes following the guidelines above
3. Run relevant tests (before and after)
4. Commit with proper message format
5. Report back with commit hash and test results

Good luck! Focus on correctness and minimal changes.
"""

    return prompt


def main():
    """
    Main orchestration loop.

    NOTE: This script generates task prompts but the actual subagent spawning
    must be done by the orchestrator agent (not this Python script).
    """

    print("=" * 80)
    print("EXCEPTION HYGIENE FIX ORCHESTRATOR - SETUP")
    print("=" * 80)
    print()

    # Configuration
    BATCH_SIZE = 3

    print("Configuration:")
    print(f"  - Batch size: {BATCH_SIZE} issues per iteration")
    print()

    # Run linter to get initial findings
    all_findings = run_linter()

    if not all_findings:
        print("\n✅ No exception hygiene issues found! All done.")
        return 0

    print(f"\nFound {len(all_findings)} total issues to fix")

    # Group into batches
    batches = group_findings_into_batches(all_findings, BATCH_SIZE)
    total_batches = len(batches)

    print(f"Created {total_batches} batches of up to {BATCH_SIZE} issues each")
    print()

    # Generate all task prompts
    print("Generating task prompts for all batches...")

    task_prompts_dir = project_root / "dev" / "artifacts" / "exception_hygiene_tasks"
    task_prompts_dir.mkdir(parents=True, exist_ok=True)

    # Clear old prompts
    for old_prompt in task_prompts_dir.glob("*.md"):
        old_prompt.unlink()

    for iteration, batch in enumerate(batches, start=1):
        task_prompt = create_fix_task_prompt(batch, iteration, total_batches)
        prompt_file = task_prompts_dir / f"task_{iteration:03d}.md"
        prompt_file.write_text(task_prompt, encoding="utf-8")

    print(f"[OK] Generated {total_batches} task prompts in: {task_prompts_dir}")
    print()

    # Save batch metadata for the orchestrator
    metadata = {
        "total_batches": total_batches,
        "total_issues": len(all_findings),
        "batch_size": BATCH_SIZE,
        "batches": [
            {
                "iteration": i,
                "issues": [
                    {
                        "code": f["code"],
                        "filename": f["filename"],
                        "lineno": f["lineno"],
                        "message": f["message"],
                    }
                    for f in batch
                ],
                "task_file": str(task_prompts_dir / f"task_{i:03d}.md"),
            }
            for i, batch in enumerate(batches, start=1)
        ],
    }

    metadata_file = task_prompts_dir / "metadata.json"
    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"[OK] Metadata saved to: {metadata_file}")
    print()

    print("=" * 80)
    print("READY FOR ORCHESTRATION")
    print("=" * 80)
    print()
    print("The orchestrator agent should now:")
    print(f"  1. Read metadata from: {metadata_file}")
    print(f"  2. For each batch (1 to {total_batches}):")
    print("     a. Read task prompt from task_NNN.md")
    print("     b. Spawn ONE zenglm subagent with that prompt")
    print("     c. Wait for subagent to complete and create commit")
    print("     d. Verify commit exists")
    print("     e. Continue to next batch")
    print("  3. After all batches, re-run linter to verify all issues are fixed")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
