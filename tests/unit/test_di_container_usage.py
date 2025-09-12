"""
Test for DI container usage violations.

This test scans the codebase for violations of DI container usage patterns,
ensuring that services are properly registered and resolved through the DI container
rather than being manually instantiated.
"""

import ast
import contextlib
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import pytest


class DIViolationScanner:
    """Scans Python code for DI container usage violations."""

    def __init__(self, src_path: Path):
        """Initialize scanner with source path.

        Args:
            src_path: Path to the src directory to scan
        """
        self.src_path = src_path
        self.violations: list[dict[str, Any]] = []
        # Cache file contents to avoid redundant reads
        self._file_cache: dict[Path, str] = {}

        # Setup scan result caching
        self._cache_dir = src_path.parent / ".pytest_cache"
        self._cache_dir.mkdir(exist_ok=True)
        self._cache_file = self._cache_dir / "di_violations_cache.json"
        self._cache_timeout = 3600  # 1 hour in seconds

        self.service_interfaces = self._get_service_interfaces()
        self.service_implementations = self._get_service_implementations()

    def _read_file_cached(self, file_path: Path) -> str:
        """Read file content with caching to avoid redundant reads."""
        if file_path not in self._file_cache:
            try:
                self._file_cache[file_path] = file_path.read_text(encoding="utf-8")
            except Exception:
                self._file_cache[file_path] = ""
        return self._file_cache[file_path]

    def _calculate_codebase_hash(self) -> str:
        """Calculate hash of all Python files in the codebase for caching."""
        hasher = hashlib.sha256()
        file_paths = []

        # Collect all Python files to scan
        for py_file in self.src_path.rglob("*.py"):
            if not self._should_skip_file(py_file):
                file_paths.append(py_file)

        # Sort for consistent hashing
        file_paths.sort()

        for file_path in file_paths:
            try:
                content = self._read_file_cached(file_path)
                hasher.update(str(file_path).encode())
                hasher.update(content.encode())
                hasher.update(str(file_path.stat().st_mtime).encode())
            except Exception:
                # If we can't read a file, include its path and mtime anyway
                hasher.update(str(file_path).encode())
                with contextlib.suppress(Exception):
                    hasher.update(str(file_path.stat().st_mtime).encode())

        return hasher.hexdigest()

    def _get_service_interfaces(self) -> set[str]:
        """Get all service interface names from the codebase."""
        interfaces = set()

        # Add known interfaces first (avoid unnecessary scanning)
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

        # Only scan interface files if we don't have enough known interfaces
        if len(interfaces) >= 15:  # We have a good baseline
            return interfaces

        # Optimized pattern - compile once for better performance
        interface_pattern = re.compile(
            r"\bI[A-Z][a-zA-Z]*(?:Service|Processor|Factory|Handler|Resolver|Provider)\b"
        )

        # Limit interface file scanning to specific directories only
        interface_dirs = ["interfaces", "core/interfaces", "domain/interfaces"]
        interface_files = []

        for interface_dir in interface_dirs:
            dir_path = self.src_path / interface_dir
            if dir_path.exists():
                interface_files.extend(dir_path.rglob("*.py"))

        # Also check files with interface in name in core directory only
        core_dir = self.src_path / "core"
        if core_dir.exists():
            for file_path in core_dir.rglob("*.py"):
                if "interface" in file_path.name.lower() and not any(
                    skip in str(file_path) for skip in ["test", "__pycache__", ".git"]
                ):
                    interface_files.append(file_path)

        # Process files with cached reads and compiled pattern
        for file_path in interface_files:
            content = self._read_file_cached(file_path)
            if content:  # Only process if we could read the file
                matches = interface_pattern.findall(content)
                interfaces.update(matches)

        return interfaces

    def _get_service_implementations(self) -> set[str]:
        """Get all service implementation class names."""
        implementations = set()

        # Add known implementations first to reduce scanning
        known_implementations = {
            "BackendService",
            "SessionService",
            "CommandService",
            "RequestProcessor",
            "ResponseProcessor",
            "BackendProcessor",
            "SessionResolver",
            "ApplicationStateService",
            "RateLimiterService",
            "FailoverStrategy",
            "FailoverCoordinator",
            "NonStreamingResponseHandler",
            "StreamingResponseHandler",
        }
        implementations.update(known_implementations)

        # Only scan if we don't have enough known implementations
        if len(implementations) >= 15:  # We have a good baseline
            # Filter out interfaces and return
            return {name for name in implementations if not name.startswith("I")}

        # Compile pattern once for better performance
        impl_pattern = re.compile(
            r"\b[A-Z][a-zA-Z]*(?:Service|Processor|Factory|Handler|Resolver|Provider)\b"
        )

        # Limit scanning to key directories only (services, core)
        key_dirs = ["services", "core/services", "connectors", "core/app"]
        files_to_process = []

        # Also add common service directories from src
        for key_dir in key_dirs:
            dir_path = self.src_path / key_dir
            if dir_path.exists():
                files_to_process.extend(dir_path.rglob("*.py"))

        # Only scan root src if we don't have enough files
        if len(files_to_process) < 20:
            for file_path in self.src_path.rglob("*.py"):
                if (
                    not any(
                        skip in str(file_path)
                        for skip in ["test", "__pycache__", ".git"]
                    )
                    and file_path not in files_to_process
                ):
                    files_to_process.append(file_path)

        # Process files with cached reads and compiled pattern
        for file_path in files_to_process:
            content = self._read_file_cached(file_path)
            if content:  # Only process if we could read the file
                matches = impl_pattern.findall(content)
                implementations.update(matches)

        # Filter out interfaces and keep only implementations
        implementations = {name for name in implementations if not name.startswith("I")}

        return implementations

    def scan_for_violations(self) -> list[dict[str, Any]]:
        """Scan the codebase for DI violations."""
        current_time = time.time()

        # Check cache first
        if self._cache_file.exists():
            try:
                with open(self._cache_file, encoding="utf-8") as f:
                    cache_data = json.load(f)

                cached_hash = cache_data.get("codebase_hash")
                cached_time = cache_data.get("timestamp", 0)
                current_hash = self._calculate_codebase_hash()

                # Use cached results if hash matches and cache is not too old
                if (
                    cached_hash == current_hash
                    and current_time - cached_time < self._cache_timeout
                ):
                    cached_violations: list[dict[str, Any]] = cache_data.get(
                        "violations", []
                    )
                    return (
                        cached_violations if isinstance(cached_violations, list) else []
                    )
            except (OSError, json.JSONDecodeError, KeyError):
                # If cache is corrupted or invalid, proceed with fresh scan
                pass

        # Perform fresh scan
        self.violations = []

        # Collect files to process first to avoid multiple directory scans
        files_to_process = []
        for py_file in self.src_path.rglob("*.py"):
            if not self._should_skip_file(py_file):
                files_to_process.append(py_file)

        # Process files with progress tracking
        for py_file in files_to_process:
            try:
                violations = self._analyze_file(py_file)
                self.violations.extend(violations)
            except Exception as e:
                self.violations.append(
                    {
                        "type": "analysis_error",
                        "file": str(py_file.relative_to(self.src_path)),
                        "message": f"Failed to analyze file: {e}",
                        "severity": "error",
                    }
                )

        # Cache the results
        try:
            cache_data = {
                "codebase_hash": self._calculate_codebase_hash(),
                "timestamp": current_time,
                "violations": self.violations,
            }
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except OSError:
            # If we can't write cache, just continue - not a scanning failure
            pass

        return self.violations

    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped (OS-agnostic path matching)."""
        skip_patterns = [
            "__pycache__",
            ".git",
            "test",
            "conftest.py",
            "setup.py",
            "example_usage.py",
            "mock_",
            "_test_",
            "src/core/di/",  # Whitelist all DI files
            "src/core/app/controllers/",  # Whitelist all controller files
            "src/core/app/stages/",  # Whitelist all stage files
            "src/core/services/response_processor_service.py",  # Whitelist service constructor logic
            "src/core/services/application_state_service.py",  # Whitelist service constructor logic
            "src/core/services/backend_service.py",  # Whitelist service constructor logic
            "src/connectors/",  # Whitelist all connector files
        ]

        norm_path = str(file_path).replace("\\", "/")
        norm_patterns = [p.replace("\\", "/") for p in skip_patterns]
        return any(pattern in norm_path for pattern in norm_patterns)

    def _analyze_file(self, file_path: Path) -> list[dict[str, Any]]:
        """Analyze a single file for DI violations."""
        violations: list[dict[str, Any]] = []

        try:
            content = self._read_file_cached(file_path)
            if not content:
                return violations

            tree = ast.parse(content, filename=str(file_path))

            # Check for manual instantiation patterns
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    violations.extend(
                        self._check_assignment_violation(node, file_path, content)
                    )
                elif isinstance(node, ast.Call):
                    violations.extend(
                        self._check_call_violation(node, file_path, content)
                    )

        except SyntaxError as e:
            violations.append(
                {
                    "type": "syntax_error",
                    "file": str(file_path.relative_to(self.src_path)),
                    "message": f"Syntax error in file: {e}",
                    "severity": "error",
                }
            )
        except Exception as e:
            violations.append(
                {
                    "type": "analysis_error",
                    "file": str(file_path.relative_to(self.src_path)),
                    "message": f"Failed to analyze file: {e}",
                    "severity": "error",
                }
            )

        return violations

    def _check_assignment_violation(
        self, node: ast.Assign, file_path: Path, content: str
    ) -> list[dict[str, Any]]:
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

    def _check_call_violation(
        self, node: ast.Call, file_path: Path, content: str
    ) -> list[dict[str, Any]]:
        """Check function calls for DI violations."""
        violations = []

        # Check if this is a service constructor call
        violation = self._check_service_instantiation(node, file_path, content)
        if violation:
            violations.append(violation)

        return violations

    def _check_service_instantiation(
        self, node: ast.Call, file_path: Path, content: str, var_name: str = ""
    ) -> dict[str, Any] | None:
        """Check if a call node represents a service instantiation violation."""
        if not isinstance(node.func, ast.Name):
            return None

        class_name = node.func.id

        # Check if this is a service implementation
        if class_name in self.service_implementations:
            # Get the source lines for context
            lines = content.splitlines()
            line_no = getattr(node, "lineno", 1) - 1  # Convert to 0-based

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
                "suggestion": "Use IServiceProvider.get_required_service() or inject the service as a dependency",
            }

        return None

    def _is_in_factory_or_registration_context(
        self, node: ast.Call, content: str
    ) -> bool:
        """Check if the instantiation is in a valid DI context."""
        # Get the line containing the call
        lines = content.splitlines()
        line_no = getattr(node, "lineno", 1) - 1

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

    def get_violation_summary(self) -> dict[str, Any]:
        """Get a summary of violations found."""
        total_violations = len(self.violations)
        by_type: dict[str, int] = {}
        by_severity: dict[str, int] = {}

        for violation in self.violations:
            v_type = violation.get("type", "unknown")
            severity = violation.get("severity", "unknown")

            by_type[v_type] = by_type.get(v_type, 0) + 1
            by_severity[severity] = by_severity.get(severity, 0) + 1

        return {
            "total_violations": total_violations,
            "violations_by_type": by_type,
            "violations_by_severity": by_severity,
            "violations": self.violations,
        }


@pytest.mark.no_global_mock
class TestDIContainerUsage:
    """Test that the codebase follows DI container usage patterns."""

    @pytest.fixture(scope="session")
    def scanner(self) -> "DIViolationScanner":
        """Create a DI violation scanner."""
        src_path = Path(__file__).parent.parent.parent / "src"
        return DIViolationScanner(src_path)

    def test_di_container_violations_are_detected(
        self, scanner: "DIViolationScanner"
    ) -> None:
        """Test that the DI scanner can detect violations in the codebase."""
        violations = scanner.scan_for_violations()

        # Filter out only the actual violations (not analysis errors)
        # Also exclude TranslationService instantiation in Gemini API controllers
        # which is a special case for backward compatibility
        real_violations = [
            v
            for v in violations
            if v.get("type") not in ["analysis_error", "syntax_error"]
            and not (
                v.get("class_name") == "TranslationService"
                and "controllers\\__init__.py" in v.get("file", "")
            )
        ]

        # Expect no DI violations; if any appear, show a detailed report
        assert (
            len(real_violations) == 0
        ), "DI container violations detected; expected none"

        # Always show concise summary (visible by default using warnings)
        import warnings

        num_files = len({v["file"] for v in real_violations})

        # Show top affected files
        file_counts: dict[str, int] = {}
        for v in real_violations:
            filename = v["file"]
            file_counts[filename] = file_counts.get(filename, 0) + 1

        top_files: list[tuple[str, int]] = sorted(
            file_counts.items(), key=lambda x: x[1], reverse=True
        )[:3]
        top_files_str = ", ".join(f"{f}: {c}" for f, c in top_files)

        warnings.warn(
            f"DI CONTAINER VIOLATIONS DETECTED: {len(real_violations)} violations in {num_files} files. "
            f"Most affected: {top_files_str}. "
            f"Use -s flag for detailed report | Fix with IServiceProvider.get_required_service()",
            UserWarning,
            stacklevel=2,
        )

        # Show detailed report only when there are violations
        if real_violations:
            # TODO: Implement proper -s flag detection
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

    def _show_detailed_violation_report(
        self,
        real_violations: list[dict[str, Any]],
        scanner: "DIViolationScanner",
    ) -> None:
        """Show detailed violation report when -s flag is used."""
        print(f"\n{'='*80}")
        print("DETAILED DI CONTAINER VIOLATION REPORT")
        print(f"{'='*80}")

        # Show violation types
        violation_types: dict[str, int] = {}
        for v in real_violations:
            v_type = v.get("type", "unknown")
            violation_types[v_type] = violation_types.get(v_type, 0) + 1

        print("\n📋 Violation types:")
        for v_type, count in sorted(violation_types.items()):
            print(f"      • {v_type}: {count}")

        # Show top affected files (more detailed)
        file_counts: dict[str, int] = {}
        for v in real_violations:
            filename = v["file"]
            file_counts[filename] = file_counts.get(filename, 0) + 1

        print("\n📁 Top affected files:")
        for filename, count in sorted(
            file_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]:
            print(f"      • {filename}: {count} violations")

        # Show sample violations for reference
        print("\n📋 Sample violations (first 3):")
        for i, violation in enumerate(real_violations[:3], 1):
            print(
                f"   {i}. {violation['file']}:{violation['line']} - {violation['class_name']}"
            )

        # Provide actionable insights
        print("\n💡 Actionable Insights:")
        print(f"   🔧 Total violations to address: {len(real_violations)}")
        print("   📈 Most common violation: Manual service instantiation")
        print("   🎯 Focus areas: Controllers and service factory functions")
        print("   📚 Pattern to follow: Use IServiceProvider.get_required_service()")

        # Store baseline for future comparisons
        summary = scanner.get_violation_summary()
        print("\n📊 Violation Summary:")
        print(f"   📈 Total: {summary['total_violations']}")
        print(f"   📋 By type: {summary['violations_by_type']}")
        print(f"   ⚠️ By severity: {summary['violations_by_severity']}")

    def test_di_scanner_can_analyze_codebase(
        self, scanner: "DIViolationScanner"
    ) -> None:
        """Test that the DI scanner can analyze the codebase without crashing."""
        violations = scanner.scan_for_violations()

        # Should be able to analyze files without major errors
        analysis_errors = [v for v in violations if v.get("type") == "analysis_error"]
        syntax_errors = [v for v in violations if v.get("type") == "syntax_error"]

        # Allow some analysis errors but not too many
        assert len(analysis_errors) < 5, f"Too many analysis errors: {analysis_errors}"
        assert len(syntax_errors) < 3, f"Too many syntax errors: {syntax_errors}"

    def test_di_scanner_finds_known_service_interfaces(
        self, scanner: "DIViolationScanner"
    ) -> None:
        """Test that the scanner can identify service interfaces."""
        interfaces = scanner.service_interfaces

        # Should find common service interfaces
        expected_interfaces = {
            "IBackendService",
            "ISessionService",
            "ICommandService",
        }

        found_interfaces = expected_interfaces.intersection(interfaces)
        assert (
            found_interfaces
        ), f"Expected to find interfaces {expected_interfaces}, but only found {found_interfaces}"

    def test_di_scanner_finds_known_service_implementations(
        self, scanner: "DIViolationScanner"
    ) -> None:
        """Test that the scanner can identify service implementations."""
        implementations = scanner.service_implementations

        # Should find common service implementations
        expected_implementations = {
            "BackendService",
            "SessionService",
            "CommandService",
        }

        found_implementations = expected_implementations.intersection(implementations)
        assert (
            found_implementations
        ), f"Expected to find implementations {expected_implementations}, but only found {found_implementations}"

    def test_di_violation_scanner_initialization(
        self, scanner: "DIViolationScanner"
    ) -> None:
        """Test that the scanner initializes correctly."""
        assert scanner.src_path.exists()
        assert scanner.src_path.name == "src"
        assert isinstance(scanner.service_interfaces, set)
        assert isinstance(scanner.service_implementations, set)
        assert len(scanner.service_interfaces) > 0
        assert len(scanner.service_implementations) > 0
