#!/usr/bin/env python3
"""
Script to analyze Kiro specs and move completed ones to archive.

Completed specs are identified by:
- phase: "implementation-complete", "completed", or "closed"
- implementation_status: "complete"
- status: "implemented", "completed", or "finished"
- implementation_completed: true
- completed_at field present
- Completion marker files (IMPLEMENTATION_COMPLETE.md, COMPLETENESS_REPORT.md, etc.)

Usage:
    python dev/scripts/archive_completed_specs.py
"""

import json
import shutil
from pathlib import Path


def load_spec_json(spec_path: Path) -> dict | None:
    """Load and parse spec.json file."""
    spec_json_path = spec_path / "spec.json"
    if not spec_json_path.exists():
        return None

    try:
        with open(spec_json_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  WARNING: Could not parse {spec_json_path}: {e}")
        return None


def has_completion_marker_file(spec_path: Path) -> bool:
    """Check if spec folder has completion marker files."""
    completion_markers = [
        "IMPLEMENTATION_COMPLETE.md",
        "COMPLETENESS_REPORT.md",
        "FINAL_STATUS.md",
        "FINAL_COMPLETION_REPORT.md",
    ]

    for marker in completion_markers:
        if (spec_path / marker).exists():
            return True
    return False


def is_completed(spec_data: dict, spec_path: Path) -> bool:
    """Check if a spec is marked as completed."""
    # First check for completion marker files
    if has_completion_marker_file(spec_path):
        return True

    if not spec_data:
        return False

    # Check phase
    phase = spec_data.get("phase", "").lower()
    if phase in ("implementation-complete", "completed", "closed", "implemented"):
        return True

    # Check implementation_status
    impl_status = spec_data.get("implementation_status", "").lower()
    if impl_status == "complete":
        return True

    # Check status field
    status = spec_data.get("status", "").lower()
    if status in ("implemented", "completed", "finished"):
        return True

    # Check boolean flags
    if spec_data.get("implementation_completed") is True:
        return True

    # Check for completion timestamp
    if "completed_at" in spec_data or "closed_at" in spec_data:
        return True

    return False


def analyze_specs(specs_dir: Path) -> tuple[list[str], list[str]]:
    """Analyze all specs and categorize them."""
    completed = []
    pending = []

    if not specs_dir.exists():
        print(f"ERROR: Specs directory not found: {specs_dir}")
        return completed, pending

    spec_folders = [
        d for d in specs_dir.iterdir() if d.is_dir() and d.name != "archive"
    ]

    print(f"Analyzing {len(spec_folders)} specs...\n")

    for spec_folder in sorted(spec_folders):
        spec_name = spec_folder.name
        spec_data = load_spec_json(spec_folder)

        if is_completed(spec_data, spec_folder):
            completed.append(spec_name)
            phase = spec_data.get("phase", "unknown") if spec_data else "unknown"
            impl_status = (
                spec_data.get("implementation_status", "unknown")
                if spec_data
                else "unknown"
            )
            marker = (
                " (has completion marker)"
                if has_completion_marker_file(spec_folder)
                else ""
            )
            print(f"[COMPLETED] {spec_name}{marker}")
            print(f"   Phase: {phase}, Status: {impl_status}")
        else:
            pending.append(spec_name)
            phase = spec_data.get("phase", "unknown") if spec_data else "no spec.json"
            print(f"[PENDING] {spec_name} (phase: {phase})")

    return completed, pending


def move_to_archive(spec_name: str, specs_dir: Path, archive_dir: Path) -> bool:
    """Move a spec folder to archive."""
    spec_path = specs_dir / spec_name
    archive_path = archive_dir / spec_name

    if not spec_path.exists():
        print(f"  WARNING: Spec folder not found: {spec_path}")
        return False

    if archive_path.exists():
        print(f"  WARNING: Archive path already exists: {archive_path}")
        return False

    try:
        shutil.move(str(spec_path), str(archive_path))
        return True
    except Exception as e:
        print(f"  ERROR: Error moving {spec_name}: {e}")
        return False


def main():
    """Main entry point."""
    workspace_root = Path(__file__).parent.parent.parent
    specs_dir = workspace_root / ".kiro" / "specs"
    archive_dir = specs_dir / "archive"

    # Ensure archive directory exists
    archive_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("Kiro Specs Maintenance: Archive Completed Specs")
    print("=" * 70)
    print()

    # Analyze specs
    completed, pending = analyze_specs(specs_dir)

    print()
    print("=" * 70)
    print(f"Summary: {len(completed)} completed, {len(pending)} pending")
    print("=" * 70)
    print()

    if not completed:
        print("No completed specs to archive.")
        return

    # Confirm before moving
    print(f"Ready to archive {len(completed)} completed spec(s):")
    for spec_name in completed:
        print(f"   - {spec_name}")
    print()

    # Move completed specs
    print("Moving completed specs to archive...")
    print()

    moved = 0
    failed = 0

    for spec_name in completed:
        if move_to_archive(spec_name, specs_dir, archive_dir):
            print(f"  [OK] Moved: {spec_name}")
            moved += 1
        else:
            print(f"  [FAILED] Failed: {spec_name}")
            failed += 1

    print()
    print("=" * 70)
    print(f"Archive complete: {moved} moved, {failed} failed")
    print(f"Pending specs remaining: {len(pending)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
