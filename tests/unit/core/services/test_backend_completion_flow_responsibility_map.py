"""Tests for backend completion flow responsibility map.

These tests validate that the responsibility map is stable and that
architectural boundaries are maintained to prevent drift.
"""

from __future__ import annotations

import inspect

import pytest
from src.core.services.backend_completion_flow import responsibility_map
from src.core.services.backend_completion_flow.availability_checker import (
    BackendAvailabilityChecker,
)
from src.core.services.backend_completion_flow.backend_manager import BackendManager
from src.core.services.backend_completion_flow.backend_request_preparer import (
    BackendRequestPreparer,
)
from src.core.services.backend_completion_flow.completion_session_resolver import (
    CompletionSessionResolver,
)
from src.core.services.backend_completion_flow.failure_recovery_executor import (
    FailureRecoveryExecutor,
)
from src.core.services.backend_completion_flow.service import BackendCompletionFlow
from src.core.services.backend_completion_flow.usage_accounting_orchestrator import (
    UsageAccountingOrchestrator,
)
from src.core.services.backend_completion_flow.wire_capture_orchestrator import (
    WireCaptureOrchestrator,
)


class TestResponsibilityMapStructure:
    """Test that the responsibility map has correct structure."""

    def test_responsibility_map_is_not_empty(self):
        """The responsibility map should contain responsibilities."""
        assert len(responsibility_map.RESPONSIBILITY_MAP) > 0

    def test_all_responsibilities_have_required_fields(self):
        """All responsibilities should have all required fields."""
        for key, resp in responsibility_map.RESPONSIBILITY_MAP.items():
            assert resp.collaborator_name, f"Missing collaborator_name for {key}"
            assert resp.responsibility, f"Missing responsibility for {key}"
            assert resp.category, f"Missing category for {key}"
            assert resp.description, f"Missing description for {key}"
            assert isinstance(
                resp.interface_methods, list
            ), f"interface_methods must be list for {key}"
            assert isinstance(
                resp.dependencies, list
            ), f"dependencies must be list for {key}"

    def test_all_categories_are_valid(self):
        """All responsibility categories should be defined."""
        valid_categories = set(responsibility_map.RESPONSIBILITY_CATEGORIES.keys())
        used_categories = {
            resp.category for resp in responsibility_map.RESPONSIBILITY_MAP.values()
        }
        invalid_categories = used_categories - valid_categories
        assert not invalid_categories, f"Invalid categories found: {invalid_categories}"

    def test_validation_passes(self):
        """The responsibility map should pass validation."""
        result = responsibility_map.validate_responsibility_boundaries()
        assert result["valid"], f"Validation failed: {result['violations']}"


class TestResponsibilityMapCoverage:
    """Test that the responsibility map covers all collaborators."""

    @pytest.mark.parametrize(
        "collaborator_class,collaborator_name",
        [
            (BackendCompletionFlow, "BackendCompletionFlow"),
            (BackendAvailabilityChecker, "BackendAvailabilityChecker"),
            (CompletionSessionResolver, "CompletionSessionResolver"),
            (BackendRequestPreparer, "BackendRequestPreparer"),
            (BackendManager, "BackendManager"),
            (WireCaptureOrchestrator, "WireCaptureOrchestrator"),
            (UsageAccountingOrchestrator, "UsageAccountingOrchestrator"),
            (FailureRecoveryExecutor, "FailureRecoveryExecutor"),
        ],
    )
    def test_collaborator_has_responsibilities(
        self, collaborator_class, collaborator_name
    ):
        """Each collaborator should have at least one responsibility."""
        responsibilities = responsibility_map.get_responsibilities_by_collaborator(
            collaborator_name
        )
        assert (
            len(responsibilities) > 0
        ), f"Collaborator {collaborator_name} has no responsibilities in map"

    def test_all_collaborators_are_covered(self):
        """All known collaborators should be in the responsibility map."""
        known_collaborators = {
            "BackendCompletionFlow",
            "BackendAvailabilityChecker",
            "CompletionSessionResolver",
            "BackendRequestPreparer",
            "BackendManager",
            "WireCaptureOrchestrator",
            "UsageAccountingOrchestrator",
            "FailureRecoveryExecutor",
        }
        mapped_collaborators = {
            resp.collaborator_name
            for resp in responsibility_map.RESPONSIBILITY_MAP.values()
        }
        missing = known_collaborators - mapped_collaborators
        assert not missing, f"Collaborators missing from responsibility map: {missing}"


class TestResponsibilityMapInterfaceMethods:
    """Test that interface methods in the map match actual implementations."""

    @pytest.mark.parametrize(
        "collaborator_class,collaborator_name",
        [
            (BackendAvailabilityChecker, "BackendAvailabilityChecker"),
            (CompletionSessionResolver, "CompletionSessionResolver"),
            (BackendRequestPreparer, "BackendRequestPreparer"),
            (BackendManager, "BackendManager"),
            (WireCaptureOrchestrator, "WireCaptureOrchestrator"),
            (UsageAccountingOrchestrator, "UsageAccountingOrchestrator"),
            (FailureRecoveryExecutor, "FailureRecoveryExecutor"),
        ],
    )
    def test_interface_methods_exist(self, collaborator_class, collaborator_name):
        """Interface methods listed in responsibility map should exist on collaborator."""
        responsibilities = responsibility_map.get_responsibilities_by_collaborator(
            collaborator_name
        )
        actual_methods = {
            name
            for name, _ in inspect.getmembers(
                collaborator_class, predicate=inspect.isfunction
            )
        }
        actual_methods.update(
            {
                name
                for name, _ in inspect.getmembers(
                    collaborator_class, predicate=inspect.ismethod
                )
            }
        )

        for resp in responsibilities:
            for method_name in resp.interface_methods:
                # Check if method exists (could be async or sync)
                method_found = (
                    hasattr(collaborator_class, method_name)
                    or method_name in actual_methods
                )
                assert method_found, (
                    f"Method '{method_name}' listed in responsibility map "
                    f"for {collaborator_name} but not found on class"
                )


class TestResponsibilityMapBoundaries:
    """Test that responsibility boundaries prevent drift."""

    def test_no_overlapping_responsibilities(self):
        """Responsibilities should not overlap between collaborators."""
        # Group responsibilities by their key characteristics
        responsibility_signatures: dict[str, list[str]] = {}
        for key, resp in responsibility_map.RESPONSIBILITY_MAP.items():
            # Create a signature based on responsibility description
            sig = resp.responsibility.lower()
            if sig not in responsibility_signatures:
                responsibility_signatures[sig] = []
            responsibility_signatures[sig].append(f"{resp.collaborator_name}:{key}")

        # Check for exact duplicates
        duplicates = {
            sig: collabs
            for sig, collabs in responsibility_signatures.items()
            if len(collabs) > 1
        }
        # Allow same collaborator to have multiple responsibilities with same name
        # if they're different keys (e.g., different aspects of same thing)
        actual_duplicates = {
            sig: collabs
            for sig, collabs in duplicates.items()
            if len({c.split(":")[0] for c in collabs}) > 1
        }
        assert (
            not actual_duplicates
        ), f"Overlapping responsibilities found: {actual_duplicates}"

    def test_categories_are_well_distributed(self):
        """Responsibilities should be distributed across categories."""
        category_counts = {}
        for resp in responsibility_map.RESPONSIBILITY_MAP.values():
            category_counts[resp.category] = category_counts.get(resp.category, 0) + 1

        # Each category should have at least one responsibility
        for category in responsibility_map.RESPONSIBILITY_CATEGORIES:
            assert (
                category_counts.get(category, 0) > 0
            ), f"Category '{category}' has no responsibilities"

    def test_helper_functions_work(self):
        """Helper functions should return correct data."""
        # Test get_responsibilities_by_collaborator
        responsibilities = responsibility_map.get_responsibilities_by_collaborator(
            "BackendAvailabilityChecker"
        )
        assert len(responsibilities) > 0
        assert all(
            r.collaborator_name == "BackendAvailabilityChecker"
            for r in responsibilities
        )

        # Test get_responsibilities_by_category
        availability_resps = responsibility_map.get_responsibilities_by_category(
            "availability"
        )
        assert len(availability_resps) > 0
        assert all(r.category == "availability" for r in availability_resps)

        # Test get_collaborator_for_responsibility
        collaborator = responsibility_map.get_collaborator_for_responsibility(
            "availability_check"
        )
        assert collaborator == "BackendAvailabilityChecker"

        # Test with invalid key
        collaborator = responsibility_map.get_collaborator_for_responsibility(
            "nonexistent"
        )
        assert collaborator is None


class TestResponsibilityMapStability:
    """Test that the responsibility map enforces stability."""

    def test_responsibility_map_is_immutable(self):
        """The responsibility map should be immutable (frozen dataclasses)."""
        from dataclasses import FrozenInstanceError

        for resp in responsibility_map.RESPONSIBILITY_MAP.values():
            # Try to modify a field (should fail if frozen)
            # Frozen dataclasses raise FrozenInstanceError
            with pytest.raises(FrozenInstanceError):
                resp.collaborator_name = "Modified"

    def test_responsibility_map_validation_is_deterministic(self):
        """Validation should return consistent results."""
        result1 = responsibility_map.validate_responsibility_boundaries()
        result2 = responsibility_map.validate_responsibility_boundaries()
        assert result1 == result2
