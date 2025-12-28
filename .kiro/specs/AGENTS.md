# `.kiro/specs` - Spec Layout Rules

This folder contains **active** Kiro specs only. Finished specs must be moved to `./archive/`.

## Directory Layout

- `./{feature-name}/`: Active spec work (pending / in-progress).
- `./archive/{feature-name}/`: Archived specs (finished / closed / implemented).
- `./archive_allowlist.json`: Allowlist for rare archive exceptions (see below).

## What Should Stay Here (Active Specs)

Keep a spec folder in `./` only if at least one of the following is true:
- Requirements/design/tasks are not fully approved yet, or
- Implementation is not complete, or
- Tasks are still incomplete / actively being worked.

## When to Move a Spec to `./archive/`

Archive a spec when it is effectively **done** (implemented or intentionally closed) and:
- `tasks.md` is reconciled (remaining items marked completed, removed, or explicitly closed/superseded), and
- `spec.json` reflects completion (e.g. `phase` in a completed phase and/or `implementation_status: "complete"`).

If the codebase evolved and some tasks/design choices are now outdated, prefer explicitly closing those tasks (e.g. “superseded / won’t do”) before archiving, instead of trying to force old design constraints onto the current architecture.

## Automated Drift Check

Run:
- `./.venv/Scripts/python.exe -m pytest tests/test_kiro_spec_state_linter.py`

It checks common Kiro state drift patterns, including:
- Active specs that look completed but aren’t archived.
- Tasks progress vs `spec.json` completion/ready-for-implementation state.
- Archive specs not marked completed (unless allowlisted).

## Archive Allowlist

If an archived spec must remain in a non-completed JSON state, add an entry to `./archive_allowlist.json`:
- `{ "spec": "<feature-name>", "reason": "<why this exception exists>" }`

