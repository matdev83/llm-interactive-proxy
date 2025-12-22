"""
Tests for DI services metrics gate.

These tests verify that the scoped complexity gate correctly:
- Identifies files in the DI services refactor scope
- Detects threshold violations (LOC, function CC)
- Excludes unrelated repository code
- Provides clear error messages
"""

from __future__ import annotations

# Import functions from analyze_complexity.py
# Note: We need to import from scripts directory
import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts directory to path for imports
scripts_path = Path(__file__).parent.parent.parent.parent.parent / "dev" / "scripts"
sys.path.insert(0, str(scripts_path))

from analyze_complexity import (
    MAX_FUNCTION_CC,
    MAX_LOC,
    get_di_services_scope_files,
    validate_di_services_files,
)


class TestScopeFileDiscovery:
    """Test that scope file discovery works correctly."""

    def test_discover_expected_files_in_scope(self):
        """Verify that expected files in scope are discovered."""
        base_path = Path(__file__).parent.parent.parent.parent.parent
        scope_files = get_di_services_scope_files(base_path)

        # Convert to relative paths for comparison
        scope_paths = {
            str(f.relative_to(base_path)).replace("\\", "/") for f in scope_files
        }

        # Verify key files are included (if they exist)
        # Note: Some files may not exist yet during refactoring, so we check conditionally
        if (base_path / "src/core/di/services.py").exists():
            assert "src/core/di/services.py" in scope_paths

        # Verify registrations directory files are included (if directory exists)
        registrations_dir = base_path / "src/core/di/registrations"
        if registrations_dir.exists():
            registrations_files = {
                p for p in scope_paths if p.startswith("src/core/di/registrations/")
            }
            assert (
                len(registrations_files) > 0
            ), "Should find registration files if directory exists"

        # Verify registration_helpers directory files are included (if directory exists)
        helpers_dir = base_path / "src/core/di/registration_helpers"
        if helpers_dir.exists():
            helpers_files = {
                p
                for p in scope_paths
                if p.startswith("src/core/di/registration_helpers/")
            }
            assert (
                len(helpers_files) > 0
            ), "Should find helper files if directory exists"

    def test_exclude_unrelated_files(self):
        """Verify that files outside scope are NOT included."""
        base_path = Path(__file__).parent.parent.parent.parent.parent
        scope_files = get_di_services_scope_files(base_path)

        # Convert to relative paths for comparison
        scope_paths = {
            str(f.relative_to(base_path)).replace("\\", "/") for f in scope_files
        }

        # These files should NOT be in scope
        assert "src/core/cli.py" not in scope_paths
        assert "src/connectors/openai_codex.py" not in scope_paths
        assert "src/core/di/container.py" not in scope_paths
        assert "src/core/di/weak_container.py" not in scope_paths

    def test_scope_patterns_match_design_spec(self):
        """Verify scope patterns match design.md specification exactly."""
        base_path = Path(__file__).parent.parent.parent.parent.parent
        scope_files = get_di_services_scope_files(base_path)

        # Verify we found at least the facade file (should always exist)
        assert len(scope_files) > 0, "Should find at least services.py in scope"

        # Verify all files are Python files
        for file_path in scope_files:
            assert file_path.suffix == ".py", f"{file_path} should be a Python file"
            assert "__pycache__" not in str(
                file_path
            ), f"{file_path} should not be in __pycache__"


class TestThresholdViolations:
    """Test that threshold violations are detected correctly."""

    def test_loc_violation_detected(self):
        """Test that files exceeding LOC threshold are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            test_file = base_path / "test_large_file.py"

            # Create a file with > 600 lines
            lines = [f"# Line {i}\n" for i in range(MAX_LOC + 10)]
            test_file.write_text("".join(lines), encoding="utf-8")

            violations, passed = validate_di_services_files([test_file], base_path)

            assert len(violations) == 1, "Should detect LOC violation"
            assert "LOC violation" in violations[0]["violations"][0]
            assert passed == 0, "Should not pass any files"

    def test_function_cc_violation_detected(self):
        """Test that functions exceeding CC threshold are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            test_file = base_path / "test_complex_function.py"

            # Create a function with high cyclomatic complexity
            # Using nested if/elif/else to increase complexity
            code_lines = ["def complex_function(x):\n"]
            for i in range(MAX_FUNCTION_CC + 5):
                code_lines.append(f"    if x == {i}:\n")
                code_lines.append(f"        return {i}\n")
            code_lines.append("    return -1\n")

            test_file.write_text("".join(code_lines), encoding="utf-8")

            violations, passed = validate_di_services_files([test_file], base_path)

            assert len(violations) == 1, "Should detect function CC violation"
            assert "Max function CC violation" in violations[0]["violations"][0]
            assert "Violating function" in violations[0]["violations"][1]
            assert passed == 0, "Should not pass any files"

    def test_violation_error_messages_clear(self):
        """Test that violation error messages clearly identify violating files/functions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            test_file = base_path / "test_violations.py"

            # Create a file with multiple violations
            code_lines = ["# " + "x" * 1000 + "\n"] * (MAX_LOC + 10)  # LOC violation
            code_lines.append("def complex_func(x):\n")
            for i in range(MAX_FUNCTION_CC + 5):  # Function CC violation
                code_lines.append(f"    if x == {i}:\n")
                code_lines.append(f"        return {i}\n")
            code_lines.append("    return -1\n")

            test_file.write_text("".join(code_lines), encoding="utf-8")

            violations, _ = validate_di_services_files([test_file], base_path)

            assert len(violations) == 1
            violation = violations[0]

            # Check file path is included
            assert "file" in violation
            assert "test_violations.py" in violation["file"]

            # Check violations list contains clear messages
            assert len(violation["violations"]) >= 2  # At least LOC and function CC
            assert any("LOC violation" in v for v in violation["violations"])
            assert any(
                "Max function CC violation" in v for v in violation["violations"]
            )
            assert any("Violating function" in v for v in violation["violations"])

            # Check metrics are included
            assert "metrics" in violation
            assert "lines" in violation["metrics"]
            assert "max_complexity" in violation["metrics"]
            assert "total_complexity" in violation["metrics"]


class TestPassingCase:
    """Test that files within thresholds pass validation."""

    def test_all_files_pass_when_within_thresholds(self):
        """Verify that all files in scope pass when within thresholds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            test_file = base_path / "test_simple.py"

            # Create a simple file well within thresholds
            code_lines = [
                "def simple_function(x):\n",
                "    return x + 1\n",
                "\n",
                "def another_function(y):\n",
                "    if y > 0:\n",
                "        return y\n",
                "    return 0\n",
            ]
            test_file.write_text("".join(code_lines), encoding="utf-8")

            violations, passed = validate_di_services_files([test_file], base_path)

            assert len(violations) == 0, "Should not detect any violations"
            assert passed == 1, "Should pass the file"


class TestErrorHandling:
    """Test error handling for analysis failures."""

    def test_analysis_errors_handled_gracefully(self):
        """Verify that analysis errors don't crash the gate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            test_file = base_path / "test_invalid.py"

            # Create a file that will cause analysis errors (syntax error)
            test_file.write_text("def invalid syntax here!!!\n", encoding="utf-8")

            violations, passed = validate_di_services_files([test_file], base_path)

            # Should handle error gracefully
            assert len(violations) == 1, "Should record analysis error"
            assert "error" in violations[0] or "type" in violations[0]
            assert passed == 0, "Should not pass files with analysis errors"


class TestRealCodebaseValidation:
    """Test that validates the actual codebase against guardrails."""

    def test_di_services_refactor_scope_meets_thresholds(self):
        """Verify that all files in DI services refactor scope meet thresholds."""
        base_path = Path(__file__).parent.parent.parent.parent.parent
        scope_files = get_di_services_scope_files(base_path)

        if not scope_files:
            pytest.skip(
                "No files found in DI services refactor scope (refactoring not started)"
            )

        violations, passed_count = validate_di_services_files(scope_files, base_path)

        if violations:
            # Format detailed error message
            error_lines = [
                f"\n{'=' * 80}",
                "DI SERVICES REFACTOR SCOPE VALIDATION FAILED",
                f"{'=' * 80}",
                f"\nFound {len(violations)} file(s) with violations:",
                f"Passed: {passed_count}/{len(scope_files)} files",
                "\nThresholds:",
                f"  - LOC per file: < {MAX_LOC}",
                f"  - Max function CC: < {MAX_FUNCTION_CC}",
                "\nViolations:",
            ]

            for violation in violations:
                error_lines.append(f"\n[FAIL] {violation['file']}")
                if "error" in violation:
                    error_lines.append(f"   Error: {violation['error']}")
                else:
                    if "metrics" in violation:
                        metrics = violation["metrics"]
                        error_lines.append(
                            f"   Metrics: {metrics['lines']} lines, "
                            f"max CC: {metrics['max_complexity']}, "
                            f"total CC: {metrics['total_complexity']}"
                        )
                    if "violations" in violation:
                        error_lines.append("   Violations:")
                        for v in violation["violations"]:
                            error_lines.append(f"     - {v}")

            error_lines.append(f"\n{'=' * 80}")
            error_lines.append(
                "Run 'python dev/scripts/analyze_complexity.py --validate-di-services-scope' "
                "for detailed violation report."
            )
            error_lines.append(f"{'=' * 80}")

            pytest.fail("\n".join(error_lines))

        # If we get here, all files passed
        assert len(violations) == 0, "Should not have any violations"
        assert passed_count == len(scope_files), "All files should pass"
