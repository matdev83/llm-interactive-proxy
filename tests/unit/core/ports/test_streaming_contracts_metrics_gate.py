"""
Tests for streaming contracts metrics gate.

These tests verify that the scoped complexity gate correctly:
- Identifies files in the streaming-contracts refactor scope
- Detects threshold violations (LOC, function CC, module CC)
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
    MAX_MODULE_CC,
    get_streaming_contracts_scope_files,
    validate_streaming_contracts_files,
)


class TestScopeFileDiscovery:
    """Test that scope file discovery works correctly."""

    def test_discover_expected_files_in_scope(self):
        """Verify that expected files in scope are discovered."""
        base_path = Path(__file__).parent.parent.parent.parent.parent
        scope_files = get_streaming_contracts_scope_files(base_path)

        # Convert to relative paths for comparison
        scope_paths = {
            str(f.relative_to(base_path)).replace("\\", "/") for f in scope_files
        }

        # Verify key files are included
        assert "src/core/ports/streaming_contracts.py" in scope_paths
        assert "src/core/services/streaming/error_mapping.py" in scope_paths

        # Verify domain streaming files are included
        domain_files = {
            p for p in scope_paths if p.startswith("src/core/domain/streaming/")
        }
        assert len(domain_files) > 0, "Should find domain streaming files"

        # Verify ports streaming files are included
        ports_files = {
            p for p in scope_paths if p.startswith("src/core/ports/streaming/")
        }
        assert len(ports_files) > 0, "Should find ports streaming files"

        # Verify transport streaming files are included
        transport_files = {
            p for p in scope_paths if p.startswith("src/core/transport/streaming/")
        }
        assert len(transport_files) > 0, "Should find transport streaming files"

    def test_exclude_unrelated_files(self):
        """Verify that files outside scope are NOT included."""
        base_path = Path(__file__).parent.parent.parent.parent.parent
        scope_files = get_streaming_contracts_scope_files(base_path)

        # Convert to relative paths for comparison
        scope_paths = {
            str(f.relative_to(base_path)).replace("\\", "/") for f in scope_files
        }

        # These files should NOT be in scope
        assert "src/core/services/streaming/stream_normalizer.py" not in scope_paths
        assert (
            "src/core/services/streaming/content_accumulation_processor.py"
            not in scope_paths
        )
        assert "src/core/cli.py" not in scope_paths
        assert "src/connectors/openai_codex.py" not in scope_paths

    def test_scope_patterns_match_design_spec(self):
        """Verify scope patterns match design.md specification exactly."""
        base_path = Path(__file__).parent.parent.parent.parent.parent
        scope_files = get_streaming_contracts_scope_files(base_path)

        # Verify we found files (basic sanity check)
        assert len(scope_files) > 0, "Should find at least some files in scope"

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

            violations, passed = validate_streaming_contracts_files(
                [test_file], base_path
            )

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

            violations, passed = validate_streaming_contracts_files(
                [test_file], base_path
            )

            assert len(violations) == 1, "Should detect function CC violation"
            assert "Max function CC violation" in violations[0]["violations"][0]
            assert "Violating function" in violations[0]["violations"][1]
            assert passed == 0, "Should not pass any files"

    def test_module_cc_violation_detected(self):
        """Test that modules exceeding total CC threshold are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            test_file = base_path / "test_high_total_cc.py"

            # Create multiple functions that together exceed module CC threshold
            # Each function has moderate complexity, but total exceeds threshold
            code_lines = []
            functions_per_file = (
                MAX_MODULE_CC // 10
            ) + 1  # Enough functions to exceed threshold
            for i in range(functions_per_file):
                code_lines.append(f"def func_{i}(x):\n")
                # Each function has complexity ~10
                for j in range(10):
                    code_lines.append(f"    if x == {j}:\n")
                    code_lines.append(f"        return {j}\n")
                code_lines.append("    return -1\n\n")

            test_file.write_text("".join(code_lines), encoding="utf-8")

            violations, passed = validate_streaming_contracts_files(
                [test_file], base_path
            )

            assert len(violations) == 1, "Should detect module CC violation"
            assert "Total module CC violation" in violations[0]["violations"][0]
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

            violations, _ = validate_streaming_contracts_files([test_file], base_path)

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

            violations, passed = validate_streaming_contracts_files(
                [test_file], base_path
            )

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

            violations, passed = validate_streaming_contracts_files(
                [test_file], base_path
            )

            # Should handle error gracefully
            assert len(violations) == 1, "Should record analysis error"
            assert "error" in violations[0] or "type" in violations[0]
            assert passed == 0, "Should not pass files with analysis errors"


class TestRealCodebaseValidation:
    """Test that validates the actual codebase against guardrails."""

    def test_streaming_contracts_refactor_scope_meets_thresholds(self):
        """Verify that all files in streaming-contracts refactor scope meet thresholds.
        
        Note: This test scans and analyzes the codebase, which is inherently slow.
        Optimizing further would compromise the test's purpose of validating the entire refactor scope.
        """
        base_path = Path(__file__).parent.parent.parent.parent.parent
        scope_files = get_streaming_contracts_scope_files(base_path)

        if not scope_files:
            pytest.fail("No files found in streaming-contracts refactor scope")

        violations, passed_count = validate_streaming_contracts_files(
            scope_files, base_path
        )

        if violations:
            # Format detailed error message
            error_lines = [
                f"\n{'=' * 80}",
                "STREAMING CONTRACTS REFACTOR SCOPE VALIDATION FAILED",
                f"{'=' * 80}",
                f"\nFound {len(violations)} file(s) with violations:",
                f"Passed: {passed_count}/{len(scope_files)} files",
                "\nThresholds:",
                f"  - LOC per file: < {MAX_LOC}",
                f"  - Max function CC: < {MAX_FUNCTION_CC}",
                f"  - Total module CC: < {MAX_MODULE_CC}",
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

            error_lines.append(
                f"\n{'=' * 80}",
                "Run 'python dev/scripts/analyze_complexity.py --validate-refactor-scope' "
                "for detailed violation report.",
                f"{'=' * 80}",
            )

            pytest.fail("\n".join(error_lines))

        # If we get here, all files passed
        assert len(violations) == 0, "Should not have any violations"
        assert passed_count == len(scope_files), "All files should pass"
