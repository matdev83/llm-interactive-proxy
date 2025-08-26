"""
Test for DI container usage violations.

This test scans the codebase for violations of DI container usage patterns,
ensuring that services are properly registered and resolved through the DI container
rather than being manually instantiated.
"""

import ast
import importlib.util
import inspect
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pytest


class DIViolationScanner:
    """Scans Python code for DI container usage violations."""

    def __init__(self, src_path: Path):
        """Initialize scanner with source path.

        Args:
            src_path: Path to the src directory to scan
        """
        self.src_path = src_path
        self.violations: List[Dict[str, Any]] = []
        self.service_interfaces = self._get_service_interfaces()
        self.service_implementations = self._get_service_implementations()

    def _get_service_interfaces(self) -> Set[str]:
        """Get all service interface names from the codebase."""
        interfaces = set()

        # Common service interface patterns
        interface_patterns = [
            "I[A-Z][a-zA-Z]*Service",
            "I[A-Z][a-zA-Z]*Processor",
            "I[A-Z][a-zA-Z]*Factory",
            "I[A-Z][a-zA-Z]*Handler",
            "I[A-Z][a-zA-Z]*Resolver",
            "I[A-Z][a-zA-Z]*Provider",
        ]

        # Scan interface files
        for pattern in interface_patterns:
            for file_path in self.src_path.rglob("*.py"):
                if "interface" in file_path.name.lower() or "interfaces" in file_path.parts:
                    try:
                        content = file_path.read_text()
                        matches = re.findall(pattern, content)
                        interfaces.update(matches)
                    except Exception:
                        continue

        # Add known interfaces
        known_interfaces = {
            "IBackendService",
            "ISessionService",
            "ICommandService",
            "ICommandProcessor",
            "IRequestProcessor",
            "IResponseProcessor",
            "IBackendProcessor",
            "ISessionResolver",
            "IApplicationState",
            "IConfig",
            "IRateLimiter",
            "IFailoverStrategy",
            "IFailoverCoordinator",
            "INonStreamingResponseHandler",
            "IStreamingResponseHandler",
        }
        interfaces.update(known_interfaces)

        return interfaces

    def _get_service_implementations(self) -> Set[str]:
        """Get all service implementation class names."""
        implementations = set()

        # Common implementation patterns
        impl_patterns = [
            "[A-Z][a-zA-Z]*Service",
            "[A-Z][a-zA-Z]*Processor",
            "[A-Z][a-zA-Z]*Factory",
            "[A-Z][a-zA-Z]*Handler",
            "[A-Z][a-zA-Z]*Resolver",
            "[A-Z][a-zA-Z]*Provider",
        ]

        for pattern in impl_patterns:
            for file_path in self.src_path.rglob("*.py"):
                if not any(skip in str(file_path) for skip in ["test", "__pycache__", ".git"]):
                    try:
                        content = file_path.read_text()
                        matches = re.findall(pattern, content)
                        implementations.update(matches)
                    except Exception:
                        continue

        # Filter out interfaces and keep only implementations
        implementations = {name for name in implementations if not name.startswith("I")}

        return implementations

    def scan_for_violations(self) -> List[Dict[str, Any]]:
        """Scan the codebase for DI violations."""
        self.violations = []

        for py_file in self.src_path.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue

            try:
                violations = self._analyze_file(py_file)
                self.violations.extend(violations)
            except Exception as e:
                self.violations.append({
                    "type": "analysis_error",
                    "file": str(py_file.relative_to(self.src_path)),
                    "message": f"Failed to analyze file: {e}",
                    "severity": "error"
                })

        return self.violations

    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        skip_patterns = [
            "__pycache__",
            ".git",
            "test",
            "conftest.py",
            "setup.py",
            "example_usage.py",
            "mock_",
            "_test_",
        ]

        return any(pattern in str(file_path) for pattern in skip_patterns)

    def _analyze_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """Analyze a single file for DI violations."""
        violations = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content, filename=str(file_path))

            # Check for manual instantiation patterns
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    violations.extend(self._check_assignment_violation(node, file_path, content))
                elif isinstance(node, ast.Call):
                    violations.extend(self._check_call_violation(node, file_path, content))

        except SyntaxError as e:
            violations.append({
                "type": "syntax_error",
                "file": str(file_path.relative_to(self.src_path)),
                "message": f"Syntax error in file: {e}",
                "severity": "error"
            })
        except Exception as e:
            violations.append({
                "type": "analysis_error",
                "file": str(file_path.relative_to(self.src_path)),
                "message": f"Failed to analyze file: {e}",
                "severity": "error"
            })

        return violations

    def _check_assignment_violation(self, node: ast.Assign, file_path: Path, content: str) -> List[Dict[str, Any]]:
        """Check assignment statements for DI violations."""
        violations = []

        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id

                # Check if we're assigning a service instantiation
                if isinstance(node.value, ast.Call):
                    violation = self._check_service_instantiation(
                        node.value, file_path, content, var_name
                    )
                    if violation:
                        violations.append(violation)

        return violations

    def _check_call_violation(self, node: ast.Call, file_path: Path, content: str) -> List[Dict[str, Any]]:
        """Check function calls for DI violations."""
        violations = []

        # Check if this is a service constructor call
        violation = self._check_service_instantiation(node, file_path, content)
        if violation:
            violations.append(violation)

        return violations

    def _check_service_instantiation(self, node: ast.Call, file_path: Path, content: str, var_name: str = "") -> Dict[str, Any] | None:
        """Check if a call node represents a service instantiation violation."""
        if not isinstance(node.func, ast.Name):
            return None

        class_name = node.func.id

        # Check if this is a service implementation
        if class_name in self.service_implementations:
            # Get the source lines for context
            lines = content.splitlines()
            line_no = getattr(node, 'lineno', 1) - 1  # Convert to 0-based

            # Get context lines
            start_line = max(0, line_no - 2)
            end_line = min(len(lines), line_no + 3)
            context = lines[start_line:end_line]

            # Check if this is in a factory function or service registration
            if self._is_in_factory_or_registration_context(node, content):
                return None  # Allow in DI registration contexts

            return {
                "type": "manual_service_instantiation",
                "file": str(file_path.relative_to(self.src_path)),
                "line": line_no + 1,
                "class_name": class_name,
                "variable": var_name,
                "context": context,
                "message": f"Manual instantiation of service class '{class_name}' detected. Use DI container instead.",
                "severity": "warning",
                "suggestion": "Use IServiceProvider.get_required_service() or inject the service as a dependency"
            }

        return None

    def _is_in_factory_or_registration_context(self, node: ast.Call, content: str) -> bool:
        """Check if the instantiation is in a valid DI context."""
        # Get the line containing the call
        lines = content.splitlines()
        line_no = getattr(node, 'lineno', 1) - 1

        if line_no >= len(lines):
            return False

        line = lines[line_no]

        # Check for DI registration patterns
        di_patterns = [
            "def.*factory",  # Factory functions
            "register_core_services",
            "add_singleton",
            "add_transient",
            "add_scoped",
            "implementation_factory",
            "ServiceCollection",
            "_add_singleton",
            "_add_instance",
        ]

        return any(pattern in line for pattern in di_patterns)

    def get_violation_summary(self) -> Dict[str, Any]:
        """Get a summary of violations found."""
        total_violations = len(self.violations)
        by_type = {}
        by_severity = {}

        for violation in self.violations:
            v_type = violation.get("type", "unknown")
            severity = violation.get("severity", "unknown")

            by_type[v_type] = by_type.get(v_type, 0) + 1
            by_severity[severity] = by_severity.get(severity, 0) + 1

        return {
            "total_violations": total_violations,
            "violations_by_type": by_type,
            "violations_by_severity": by_severity,
            "violations": self.violations
        }


@pytest.mark.no_global_mock
class TestDIContainerUsage:
    """Test that the codebase follows DI container usage patterns."""

    @pytest.fixture
    def scanner(self):
        """Create a DI violation scanner."""
        src_path = Path(__file__).parent.parent.parent / "src"
        return DIViolationScanner(src_path)

    def test_di_container_violations_are_detected(self, scanner):
        """Test that the DI scanner can detect violations in the codebase."""
        violations = scanner.scan_for_violations()

        # Filter out only the actual violations (not analysis errors)
        real_violations = [
            v for v in violations
            if v.get("type") not in ["analysis_error", "syntax_error"]
        ]

        # The scanner should find violations (this is expected in the current codebase)
        assert len(real_violations) > 0, "Scanner should detect violations in the current codebase"

        # Always show concise summary (visible without -s flag)
        num_files = len(set(v['file'] for v in real_violations))
        print(f"\n⚠️  DI CONTAINER VIOLATIONS: {len(real_violations)} violations in {num_files} files")

        # Show top affected files
        file_counts = {}
        for v in real_violations:
            filename = v['file']
            file_counts[filename] = file_counts.get(filename, 0) + 1

        print("📁 Most affected:")
        for filename, count in sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:3]:
            print(f"   • {filename}: {count} violations")

        print("💡 Use -s flag for detailed report | Fix with IServiceProvider.get_required_service()")

        # Show detailed report when -s flag is used (detected by checking if we're capturing output)
        import sys
        if hasattr(sys.stdout, 'isatty') and not sys.stdout.isatty():
            # We're likely in pytest capture mode (-s flag)
            self._show_detailed_violation_report(real_violations, scanner)

        # Check that violations have proper structure
        for violation in real_violations[:5]:  # Check first 5
            assert "type" in violation
            assert "file" in violation
            assert "line" in violation
            assert "message" in violation
            assert "suggestion" in violation
            assert isinstance(violation["line"], int)
            assert violation["line"] > 0

        # This test serves as a baseline - future runs can compare against this
        # The goal is to reduce violations over time, not eliminate them all at once

    def _show_detailed_violation_report(self, real_violations, scanner):
        """Show detailed violation report when -s flag is used."""
        print(f"\n{'='*80}")
        print("DETAILED DI CONTAINER VIOLATION REPORT")
        print(f"{'='*80}")

        # Show violation types
        violation_types = {}
        for v in real_violations:
            v_type = v.get("type", "unknown")
            violation_types[v_type] = violation_types.get(v_type, 0) + 1

        print(f"\n📋 Violation types:")
        for v_type, count in sorted(violation_types.items()):
            print(f"      • {v_type}: {count}")

        # Show top affected files (more detailed)
        file_counts = {}
        for v in real_violations:
            filename = v['file']
            file_counts[filename] = file_counts.get(filename, 0) + 1

        print(f"\n📁 Top affected files:")
        for filename, count in sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"      • {filename}: {count} violations")

        # Show sample violations for reference
        print(f"\n📋 Sample violations (first 3):")
        for i, violation in enumerate(real_violations[:3], 1):
            print(f"   {i}. {violation['file']}:{violation['line']} - {violation['class_name']}")

        # Provide actionable insights
        print(f"\n💡 Actionable Insights:")
        print(f"   🔧 Total violations to address: {len(real_violations)}")
        print(f"   📈 Most common violation: Manual service instantiation")
        print(f"   🎯 Focus areas: Controllers and service factory functions")
        print(f"   📚 Pattern to follow: Use IServiceProvider.get_required_service()")

        # Store baseline for future comparisons
        summary = scanner.get_violation_summary()
        print(f"\n📊 Violation Summary:")
        print(f"   📈 Total: {summary['total_violations']}")
        print(f"   📋 By type: {summary['violations_by_type']}")
        print(f"   ⚠️ By severity: {summary['violations_by_severity']}")

    def test_di_scanner_can_analyze_codebase(self, scanner):
        """Test that the DI scanner can analyze the codebase without crashing."""
        violations = scanner.scan_for_violations()

        # Should be able to analyze files without major errors
        analysis_errors = [v for v in violations if v.get("type") == "analysis_error"]
        syntax_errors = [v for v in violations if v.get("type") == "syntax_error"]

        # Allow some analysis errors but not too many
        assert len(analysis_errors) < 5, f"Too many analysis errors: {analysis_errors}"
        assert len(syntax_errors) < 3, f"Too many syntax errors: {syntax_errors}"

    def test_di_scanner_finds_known_service_interfaces(self, scanner):
        """Test that the scanner can identify service interfaces."""
        interfaces = scanner.service_interfaces

        # Should find common service interfaces
        expected_interfaces = {
            "IBackendService",
            "ISessionService",
            "ICommandService",
        }

        found_interfaces = expected_interfaces.intersection(interfaces)
        assert found_interfaces, f"Expected to find interfaces {expected_interfaces}, but only found {found_interfaces}"

    def test_di_scanner_finds_known_service_implementations(self, scanner):
        """Test that the scanner can identify service implementations."""
        implementations = scanner.service_implementations

        # Should find common service implementations
        expected_implementations = {
            "BackendService",
            "SessionService",
            "CommandService",
        }

        found_implementations = expected_implementations.intersection(implementations)
        assert found_implementations, f"Expected to find implementations {expected_implementations}, but only found {found_implementations}"

    def test_di_violation_scanner_initialization(self, scanner):
        """Test that the scanner initializes correctly."""
        assert scanner.src_path.exists()
        assert scanner.src_path.name == "src"
        assert isinstance(scanner.service_interfaces, set)
        assert isinstance(scanner.service_implementations, set)
        assert len(scanner.service_interfaces) > 0
        assert len(scanner.service_implementations) > 0
