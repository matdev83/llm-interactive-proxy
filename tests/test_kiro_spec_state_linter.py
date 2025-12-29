from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

READY_PHASES = {
    "ready-for-implementation",
    "tasks-approved",
    "tasks-generated",
}
COMPLETE_PHASES = {"implementation-complete", "completed", "closed", "implemented"}
COMPLETE_STATUSES = {"implemented", "completed", "finished"}
ARCHIVE_ALLOWLIST_FILENAME = "archive_allowlist.json"


def _load_spec_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("spec.json must contain an object")
    return data


def _load_archive_allowlist(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "entries": []}
    data = _load_spec_json(path)
    entries = data.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("archive allowlist entries must be a list")
    return data


def _is_archive_exempt(spec_name: str, allowlist: dict[str, Any]) -> bool:
    entries = allowlist.get("entries", [])
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("spec") == spec_name:
            return True
    return False


def _parse_task_progress(path: Path) -> tuple[int, int]:
    total = 0
    completed = 0
    pattern = re.compile(r"^\s*-\s*\[([ xX])\]\s+")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        total += 1
        if match.group(1).lower() == "x":
            completed += 1
    return total, completed


def _extract_spec_name(spec_data: dict[str, Any]) -> str | None:
    for key in ("feature_name", "featureName", "feature", "name"):
        value = spec_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_complete(spec_data: dict[str, Any]) -> bool:
    phase = str(spec_data.get("phase", "")).lower()
    if phase in COMPLETE_PHASES:
        return True
    if str(spec_data.get("implementation_status", "")).lower() == "complete":
        return True
    if str(spec_data.get("status", "")).lower() in COMPLETE_STATUSES:
        return True
    if spec_data.get("implementation_completed") is True:
        return True
    return "completed_at" in spec_data or "closed_at" in spec_data


def _is_ready_for_implementation(spec_data: dict[str, Any]) -> bool:
    if spec_data.get("ready_for_implementation") is True:
        return True
    phase = str(spec_data.get("phase", "")).lower()
    return phase in READY_PHASES


def _approvals_complete(spec_data: dict[str, Any]) -> bool:
    approvals = spec_data.get("approvals", {})
    if not isinstance(approvals, dict):
        return False
    for key in ("requirements", "design", "tasks"):
        entry = approvals.get(key)
        if isinstance(entry, dict):
            if entry.get("approved") is not True:
                return False
        elif entry is not True:
            return False
    return True


def _approvals_include_any(spec_data: dict[str, Any]) -> bool:
    approvals = spec_data.get("approvals", {})
    if not isinstance(approvals, dict):
        return False
    for value in approvals.values():
        if isinstance(value, dict):
            if value.get("approved") is True:
                return True
        elif value is True:
            return True
    return False


def _validate_spec_state(specs_root: Path) -> list[str]:
    errors: list[str] = []
    allowlist_path = specs_root / ARCHIVE_ALLOWLIST_FILENAME
    allowlist = _load_archive_allowlist(allowlist_path)
    
    for spec_dir in sorted(specs_root.iterdir()):
        if not spec_dir.is_dir() or spec_dir.name == "archive":
            continue

        spec_json_path = spec_dir / "spec.json"
        if not spec_json_path.exists():
            errors.append(f"{spec_dir.name}: missing spec.json")
            continue

        try:
            spec_data = _load_spec_json(spec_json_path)
        except Exception as exc:
            errors.append(f"{spec_dir.name}: invalid spec.json ({exc})")
            continue

        spec_name = _extract_spec_name(spec_data)
        if spec_name is not None and spec_name != spec_dir.name:
            errors.append(
                f"{spec_dir.name}: folder name mismatch (spec.json name={spec_name})"
            )

        phase = str(spec_data.get("phase", "")).lower()
        status = str(spec_data.get("status", "")).lower()
        impl_status = str(spec_data.get("implementation_status", "")).lower()
        approvals_complete = _approvals_complete(spec_data)
        is_complete = _is_complete(spec_data)
        is_ready = _is_ready_for_implementation(spec_data)

        if is_complete and not _is_archive_exempt(spec_dir.name, allowlist):
            errors.append(
                f"{spec_dir.name}: marked complete but not archived (move to .kiro/specs/archive)"
            )

        if phase in READY_PHASES and not approvals_complete:
            errors.append(f"{spec_dir.name}: ready phase without full approvals")
        if (
            phase in COMPLETE_PHASES
            and impl_status != "complete"
            and status not in COMPLETE_STATUSES
        ):
            errors.append(f"{spec_dir.name}: complete phase without completion status")
        if (
            impl_status == "complete"
            and phase not in COMPLETE_PHASES
            and status not in COMPLETE_STATUSES
        ):
            errors.append(
                f"{spec_dir.name}: implementation_status complete but phase/status not complete"
            )
        if (
            status in COMPLETE_STATUSES
            and phase not in COMPLETE_PHASES
            and impl_status != "complete"
        ):
            errors.append(
                f"{spec_dir.name}: status complete but phase/implementation_status not complete"
            )
        if is_ready and not approvals_complete:
            errors.append(
                f"{spec_dir.name}: ready_for_implementation true without full approvals"
            )
        if is_complete and is_ready:
            errors.append(
                f"{spec_dir.name}: marked complete but ready_for_implementation true"
            )

        tasks_path = spec_dir / "tasks.md"
        if not tasks_path.exists():
            continue

        total_tasks, completed_tasks = _parse_task_progress(tasks_path)
        if total_tasks == 0:
            continue

        if completed_tasks == total_tasks:
            if not is_complete:
                errors.append(
                    f"{spec_dir.name}: tasks complete but spec.json not marked complete"
                )
            if spec_data.get("ready_for_implementation") is True:
                errors.append(
                    f"{spec_dir.name}: tasks complete but ready_for_implementation true"
                )
            continue

        if completed_tasks == 0:
            if approvals_complete and not is_ready:
                errors.append(
                    f"{spec_dir.name}: approvals complete with no tasks done, but not ready"
                )
            if is_complete:
                errors.append(
                    f"{spec_dir.name}: no tasks done but spec.json marked complete"
                )
            if _approvals_include_any(spec_data) and not approvals_complete:
                errors.append(
                    f"{spec_dir.name}: some approvals present but not all required approved"
                )
            continue

        if is_ready or phase in READY_PHASES:
            errors.append(
                f"{spec_dir.name}: tasks in progress but spec marked ready for implementation"
            )
        if is_complete:
            errors.append(
                f"{spec_dir.name}: tasks incomplete but spec.json marked complete"
            )

    return errors


def _find_completed_unarchived_specs(specs_root: Path) -> list[str]:
    errors: list[str] = []
    allowlist_path = specs_root / ARCHIVE_ALLOWLIST_FILENAME
    allowlist = _load_archive_allowlist(allowlist_path)
    
    for spec_dir in sorted(specs_root.iterdir()):
        if not spec_dir.is_dir() or spec_dir.name == "archive":
            continue

        spec_json_path = spec_dir / "spec.json"
        tasks_path = spec_dir / "tasks.md"
        if not spec_json_path.exists() or not tasks_path.exists():
            continue

        try:
            spec_data = _load_spec_json(spec_json_path)
        except Exception as exc:
            errors.append(f"{spec_dir.name}: invalid spec.json ({exc})")
            continue

        total_tasks, completed_tasks = _parse_task_progress(tasks_path)
        if total_tasks == 0:
            continue

        if (
            completed_tasks == total_tasks
            and _is_complete(spec_data)
            and not _is_archive_exempt(spec_dir.name, allowlist)
        ):
            errors.append(
                f"{spec_dir.name}: appears complete but not archived (move to .kiro/specs/archive)"
            )

    return errors


def _write_spec(
    root: Path,
    name: str,
    spec_data: dict[str, Any],
    tasks: list[str] | None = None,
) -> Path:
    spec_dir = root / name
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.json").write_text(
        json.dumps(spec_data, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if tasks is not None:
        (spec_dir / "tasks.md").write_text("\n".join(tasks) + "\n", encoding="utf-8")
    return spec_dir


def test_kiro_spec_state_consistency() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    specs_root = repo_root / ".kiro" / "specs"
    assert specs_root.exists(), f"Missing specs directory: {specs_root}"

    errors = _validate_spec_state(specs_root)
    if errors:
        pytest.fail("Kiro spec state inconsistencies:\n" + "\n".join(errors))


def test_kiro_specs_complete_should_be_archived() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    specs_root = repo_root / ".kiro" / "specs"
    assert specs_root.exists(), f"Missing specs directory: {specs_root}"

    errors = _find_completed_unarchived_specs(specs_root)
    if errors:
        pytest.fail("Completed specs not archived:\n" + "\n".join(errors))


def test_kiro_spec_state_linter_temp_specs(tmp_path: Path) -> None:
    root = tmp_path / "specs"
    _write_spec(
        root,
        "ready-without-approvals",
        {
            "phase": "ready-for-implementation",
            "approvals": {"requirements": {"approved": False}},
        },
        tasks=["- [ ] 1. Task one"],
    )
    _write_spec(
        root,
        "complete-phase-missing-status",
        {
            "phase": "implementation-complete",
            "approvals": {
                "requirements": {"approved": True},
                "design": {"approved": True},
                "tasks": {"approved": True},
            },
        },
        tasks=["- [x] 1. Task one"],
    )
    _write_spec(
        root,
        "impl-complete-but-phase-not",
        {
            "phase": "implementation",
            "implementation_status": "complete",
            "approvals": {
                "requirements": {"approved": True},
                "design": {"approved": True},
                "tasks": {"approved": True},
            },
        },
        tasks=["- [x] 1. Task one"],
    )

    errors = _validate_spec_state(root)
    assert any("ready phase without full approvals" in err for err in errors)
    assert any("complete phase without completion status" in err for err in errors)
    assert any(
        "implementation_status complete but phase/status not complete" in err
        for err in errors
    )


def test_kiro_spec_state_linter_detects_ready_drift(tmp_path: Path) -> None:
    root = tmp_path / "specs"
    _write_spec(
        root,
        "in-progress-but-ready",
        {
            "phase": "ready-for-implementation",
            "ready_for_implementation": True,
            "approvals": {
                "requirements": {"approved": True},
                "design": {"approved": True},
                "tasks": {"approved": True},
            },
        },
        tasks=["- [x] 1. Done", "- [ ] 2. Todo"],
    )
    errors = _validate_spec_state(root)
    assert any("tasks in progress but spec marked ready" in err for err in errors)


def test_kiro_spec_state_linter_detects_folder_name_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "specs"
    _write_spec(
        root,
        "folder-a",
        {
            "feature_name": "folder-b",
            "phase": "initialized",
        },
        tasks=["- [ ] 1. Task one"],
    )
    errors = _validate_spec_state(root)
    assert any("folder name mismatch" in err for err in errors)


def test_kiro_archive_linter_temp_specs(tmp_path: Path) -> None:
    root = tmp_path / "specs"
    _write_spec(
        root,
        "complete-not-archived",
        {
            "phase": "implementation-complete",
            "implementation_status": "complete",
        },
        tasks=["- [x] 1. Task one"],
    )

    errors = _find_completed_unarchived_specs(root)
    assert any("complete-not-archived" in err for err in errors)


def _find_archive_specs_not_complete(
    archive_root: Path, allowlist: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    if not archive_root.exists():
        return errors

    for spec_dir in sorted(archive_root.iterdir()):
        if not spec_dir.is_dir():
            continue

        spec_json_path = spec_dir / "spec.json"
        if not spec_json_path.exists():
            errors.append(f"{spec_dir.name}: missing spec.json in archive")
            continue

        try:
            spec_data = _load_spec_json(spec_json_path)
        except Exception as exc:
            errors.append(f"{spec_dir.name}: invalid spec.json ({exc})")
            continue

        if _is_archive_exempt(spec_dir.name, allowlist):
            continue
        if not _is_complete(spec_data):
            errors.append(f"{spec_dir.name}: archived but not marked complete")

    return errors


def test_kiro_archive_specs_marked_complete() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    specs_root = repo_root / ".kiro" / "specs"
    archive_root = specs_root / "archive"
    allowlist_path = specs_root / ARCHIVE_ALLOWLIST_FILENAME
    allowlist = _load_archive_allowlist(allowlist_path)
    errors = _find_archive_specs_not_complete(archive_root, allowlist)
    if errors:
        pytest.fail("Archive specs not marked complete:\n" + "\n".join(errors))


def test_kiro_archive_linter_temp_specs_incomplete(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    _write_spec(
        archive_root,
        "archived-not-complete",
        {
            "phase": "implementation",
        },
        tasks=["- [x] 1. Task one"],
    )
    allowlist = {"version": 1, "entries": []}
    errors = _find_archive_specs_not_complete(archive_root, allowlist)
    assert any("archived-not-complete" in err for err in errors)


def test_kiro_archive_linter_respects_allowlist(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    _write_spec(
        archive_root,
        "archived-exempt",
        {
            "phase": "implementation",
        },
        tasks=["- [x] 1. Task one"],
    )
    allowlist = {
        "version": 1,
        "entries": [
            {"spec": "archived-exempt", "reason": "Legacy spec metadata incomplete"}
        ],
    }
    errors = _find_archive_specs_not_complete(archive_root, allowlist)
    assert not errors
