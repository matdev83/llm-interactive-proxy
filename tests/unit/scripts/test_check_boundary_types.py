"""Tests for check_boundary_types.py script."""

import sys
from pathlib import Path

# Add dev/scripts to path for imports
dev_scripts_path = Path(__file__).parent.parent.parent.parent / "dev" / "scripts"
sys.path.insert(0, str(dev_scripts_path))

from check_boundary_types import (
    BoundaryTypeChecker,
    check_boundary_types,
)


class TestBoundaryTypeChecker:
    """Test BoundaryTypeChecker detection logic."""

    def test_detects_any_in_function_signature(self):
        """Test that Any in function signature is detected."""
        code = """
from typing import Any

def process_request(request: Any) -> ResponseEnvelope:
    pass
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/interfaces/processor.py", code)
        assert len(violations) == 1
        assert (
            violations[0].message
            == "Function 'process_request' parameter 'request' uses 'Any' in signature"
        )
        assert violations[0].line == 4

    def test_detects_dict_str_any_in_function_signature(self):
        """Test that dict[str, Any] in function signature is detected."""
        code = """
from typing import Any

def process_request(request: dict[str, Any]) -> ResponseEnvelope:
    pass
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/interfaces/processor.py", code)
        assert len(violations) == 1
        assert (
            violations[0].message
            == "Function 'process_request' parameter 'request' uses 'dict[str, Any]' in signature"
        )
        assert violations[0].line == 4

    def test_allows_dict_str_jsonvalue(self):
        """Test that dict[str, JsonValue] is allowed."""
        code = """
from pydantic.types import JsonValue

def process_request(request: dict[str, JsonValue]) -> ResponseEnvelope:
    pass
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/interfaces/processor.py", code)
        assert len(violations) == 0

    def test_allows_typed_contracts(self):
        """Test that canonical contracts are allowed."""
        code = """
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.request_context import RequestContext

def process_request(request: CanonicalChatRequest, context: RequestContext) -> ResponseEnvelope:
    pass
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/interfaces/processor.py", code)
        assert len(violations) == 0

    def test_respects_allowlist(self):
        """Test that allowlisted patterns are ignored."""
        code = """
from typing import Any
from dataclasses import field

class ProcessingContext:
    values: dict[str, Any] = field(default_factory=dict)
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/domain/request_context.py", code)
        # ProcessingContext.values is allowlisted
        assert len(violations) == 0

    def test_detects_type_ignore_in_boundary_modules(self):
        """Test that type: ignore comments are detected."""
        code = """
from typing import Any

def process_request(request: Any) -> ResponseEnvelope:  # type: ignore[no-untyped-def]
    pass
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/interfaces/processor.py", code)
        assert len(violations) >= 1
        # Should detect Any (type: ignore detection not implemented yet)
        any_violations = [v for v in violations if "Any" in v.message]
        assert len(any_violations) >= 1

    def test_ignores_test_files(self):
        """Test that test files are ignored."""
        code = """
def test_something(request: Any) -> None:
    pass
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("test_file.py", code)
        assert len(violations) == 0

    def test_detects_any_in_method_signature(self):
        """Test that Any in method signature is detected."""
        code = """
from typing import Any

class Service:
    def process(self, request: Any) -> ResponseEnvelope:
        pass
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/interfaces/service.py", code)
        assert len(violations) == 1
        assert "process" in violations[0].message

    def test_allows_any_in_internal_contexts(self):
        """Test that Any in internal contexts (not function signatures) is allowed."""
        code = """
from typing import Any
from src.core.domain.chat import CanonicalChatRequest

def process_request(request: CanonicalChatRequest) -> ResponseEnvelope:
    internal_var: Any = some_value
    return ResponseEnvelope(content=internal_var)
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/interfaces/processor.py", code)
        # Internal variable assignments are not checked
        assert len(violations) == 0

    def test_detects_any_in_return_type(self):
        """Test that Any in return type is detected."""
        code = """
from typing import Any
from src.core.domain.chat import CanonicalChatRequest

def process_request(request: CanonicalChatRequest) -> Any:
    pass
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/interfaces/processor.py", code)
        assert len(violations) == 1
        assert (
            "return type" in violations[0].message.lower()
            or "Any" in violations[0].message
        )

    def test_allows_union_with_none(self):
        """Test that Optional/Union with None is allowed."""
        code = """
from typing import Optional
from src.core.domain.chat import CanonicalChatRequest

def process_request(request: Optional[CanonicalChatRequest]) -> ResponseEnvelope:
    pass
"""
        checker = BoundaryTypeChecker()
        violations = checker.check_file("src/core/interfaces/processor.py", code)
        assert len(violations) == 0


class TestCheckBoundaryTypes:
    """Test the main check_boundary_types function."""

    def test_returns_zero_exit_code_when_clean(self, tmp_path):
        """Test that clean codebase returns exit code 0."""
        # Create a clean Python file
        test_file = tmp_path / "test_clean.py"
        test_file.write_text(
            """
from src.core.domain.chat import CanonicalChatRequest

def process(request: CanonicalChatRequest) -> None:
    pass
"""
        )

        # Create boundary module directory
        boundary_dir = tmp_path / "src" / "core" / "interfaces"
        boundary_dir.mkdir(parents=True)
        boundary_file = boundary_dir / "test_interface.py"
        boundary_file.write_text(
            """
from src.core.domain.chat import CanonicalChatRequest

def process(request: CanonicalChatRequest) -> None:
    pass
"""
        )

        exit_code = check_boundary_types([str(tmp_path)])
        assert exit_code == 0

    def test_returns_one_exit_code_when_violations_found(self, tmp_path):
        """Test that violations return exit code 1."""
        # Create boundary module directory
        boundary_dir = tmp_path / "src" / "core" / "interfaces"
        boundary_dir.mkdir(parents=True)
        boundary_file = boundary_dir / "processor.py"
        boundary_file.write_text(
            """
from typing import Any

def process(request: Any) -> None:
    pass
"""
        )

        exit_code = check_boundary_types([str(tmp_path)])
        assert exit_code == 1

    def test_ignores_non_boundary_modules(self, tmp_path):
        """Test that non-boundary modules are ignored."""
        # Create non-boundary directory
        other_dir = tmp_path / "src" / "other"
        other_dir.mkdir(parents=True)
        other_file = other_dir / "test_other.py"
        other_file.write_text(
            """
from typing import Any

def process(request: Any) -> None:
    pass
"""
        )

        exit_code = check_boundary_types([str(tmp_path)])
        # Should not find violations in non-boundary modules
        assert exit_code == 0
