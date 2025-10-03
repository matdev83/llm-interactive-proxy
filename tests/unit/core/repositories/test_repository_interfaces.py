"""
Tests for Repository Interfaces.

This module tests the repository interface definitions and contract compliance.
"""

from abc import ABC
from typing import Generic

import pytest
from src.core.domain.usage_data import UsageData
from src.core.interfaces.repositories_interface import (
    IConfigRepository,
    IRepository,
    ISessionRepository,
    IUsageRepository,
)


class TestIRepositoryInterface:
    """Tests for IRepository interface."""

    def test_repository_is_abstract(self) -> None:
        """Test that IRepository is an abstract class."""
        assert issubclass(IRepository, ABC)
        assert issubclass(IRepository, Generic)

        # Should not be instantiable
        with pytest.raises(TypeError):
            IRepository()

    def test_repository_has_type_parameter(self) -> None:
        """Test that IRepository has a type parameter."""
        assert hasattr(IRepository, "__parameters__")
        # The type parameter should be present
        assert len(IRepository.__parameters__) == 1

    def test_repository_abstract_methods(self) -> None:
        """Test that IRepository defines all required abstract methods."""
        expected_methods = ["get_by_id", "get_all", "add", "update", "delete"]

        for method_name in expected_methods:
            assert hasattr(IRepository, method_name)

            # Check that methods are abstract
            method = getattr(IRepository, method_name)
            assert hasattr(method, "__isabstractmethod__")
            assert method.__isabstractmethod__ is True

    def test_repository_method_signatures(self) -> None:
        """Test that IRepository methods have correct signatures."""
        # get_by_id(id: str) -> T | None
        assert callable(IRepository.get_by_id)

        # get_all() -> list[T]
        assert callable(IRepository.get_all)

        # add(entity: T) -> T
        assert callable(IRepository.add)

        # update(entity: T) -> T
        assert callable(IRepository.update)

        # delete(id: str) -> bool
        assert callable(IRepository.delete)


class TestISessionRepositoryInterface:
    """Tests for ISessionRepository interface."""

    def test_session_repository_extends_repository(self) -> None:
        """Test that ISessionRepository extends IRepository."""
        assert issubclass(ISessionRepository, IRepository)
        assert issubclass(ISessionRepository, ABC)

    def test_session_repository_type_parameter(self) -> None:
        """Test that ISessionRepository is parameterized with Session."""
        # The interface should be bound to Session type (using ForwardRef)
        bases = ISessionRepository.__orig_bases__[0].__args__
        assert len(bases) == 1
        # Check that the type parameter is Session (ForwardRef)
        assert "Session" in str(bases[0])

    def test_session_repository_additional_methods(self) -> None:
        """Test that ISessionRepository defines additional abstract methods."""
        expected_methods = ["get_by_user_id", "cleanup_expired"]

        for method_name in expected_methods:
            assert hasattr(ISessionRepository, method_name)

            # Check that methods are abstract
            method = getattr(ISessionRepository, method_name)
            assert hasattr(method, "__isabstractmethod__")
            assert method.__isabstractmethod__ is True

    def test_session_repository_method_signatures(self) -> None:
        """Test that ISessionRepository methods have correct signatures."""
        # get_by_user_id(user_id: str) -> list[Session]
        assert callable(ISessionRepository.get_by_user_id)

        # cleanup_expired(max_age_seconds: int) -> int
        assert callable(ISessionRepository.cleanup_expired)


class TestIConfigRepositoryInterface:
    """Tests for IConfigRepository interface."""

    def test_config_repository_is_abstract(self) -> None:
        """Test that IConfigRepository is an abstract class."""
        assert issubclass(IConfigRepository, ABC)

    def test_config_repository_abstract_methods(self) -> None:
        """Test that IConfigRepository defines all required abstract methods."""
        expected_methods = ["get_config", "set_config", "delete_config"]

        for method_name in expected_methods:
            assert hasattr(IConfigRepository, method_name)

            # Check that methods are abstract
            method = getattr(IConfigRepository, method_name)
            assert hasattr(method, "__isabstractmethod__")
            assert method.__isabstractmethod__ is True

    def test_config_repository_method_signatures(self) -> None:
        """Test that IConfigRepository methods have correct signatures."""
        # get_config(key: str) -> dict[str, Any] | None
        assert callable(IConfigRepository.get_config)

        # set_config(key: str, config: dict[str, Any]) -> None
        assert callable(IConfigRepository.set_config)

        # delete_config(key: str) -> bool
        assert callable(IConfigRepository.delete_config)


class TestIUsageRepositoryInterface:
    """Tests for IUsageRepository interface."""

    def test_usage_repository_extends_repository(self) -> None:
        """Test that IUsageRepository extends IRepository."""
        assert issubclass(IUsageRepository, IRepository)
        assert issubclass(IUsageRepository, ABC)

    def test_usage_repository_type_parameter(self) -> None:
        """Test that IUsageRepository is parameterized with UsageData."""
        # The interface should be bound to UsageData type
        assert UsageData in IUsageRepository.__orig_bases__[0].__args__

    def test_usage_repository_additional_methods(self) -> None:
        """Test that IUsageRepository defines additional abstract methods."""
        expected_methods = ["get_by_session_id", "get_stats"]

        for method_name in expected_methods:
            assert hasattr(IUsageRepository, method_name)

            # Check that methods are abstract
            method = getattr(IUsageRepository, method_name)
            assert hasattr(method, "__isabstractmethod__")
            assert method.__isabstractmethod__ is True

    def test_usage_repository_method_signatures(self) -> None:
        """Test that IUsageRepository methods have correct signatures."""
        # get_by_session_id(session_id: str) -> list[UsageData]
        assert callable(IUsageRepository.get_by_session_id)

        # get_stats(project: str | None = None) -> dict[str, Any]
        assert callable(IUsageRepository.get_stats)


class TestRepositoryInterfaceCompliance:
    """Tests for repository interface compliance and contracts."""

    def test_repository_interfaces_are_properly_defined(self) -> None:
        """Test that all repository interfaces are properly defined."""
        interfaces = [
            IRepository,
            ISessionRepository,
            IConfigRepository,
            IUsageRepository,
        ]

        for interface in interfaces:
            assert issubclass(interface, ABC)
            assert hasattr(interface, "__annotations__")

    def test_repository_interface_inheritance_chain(self) -> None:
        """Test that repository interfaces follow proper inheritance."""
        # IRepository is the base generic interface
        from typing import Generic

        assert Generic in IRepository.__bases__
        assert ABC in IRepository.__bases__

        # Specialized repositories extend IRepository
        assert IRepository in ISessionRepository.__mro__
        assert IRepository in IUsageRepository.__mro__

        # IConfigRepository is standalone (doesn't extend IRepository)
        assert IRepository not in IConfigRepository.__mro__

    def test_repository_has_required_methods(self) -> None:
        """Test that repository interfaces have the required methods."""
        # Test IRepository methods
        assert hasattr(IRepository, "get_by_id")
        assert hasattr(IRepository, "get_all")
        assert hasattr(IRepository, "add")
        assert hasattr(IRepository, "update")
        assert hasattr(IRepository, "delete")

        # Test specialized repository methods
        assert hasattr(ISessionRepository, "get_by_user_id")
        assert hasattr(ISessionRepository, "cleanup_expired")

        assert hasattr(IConfigRepository, "get_config")
        assert hasattr(IConfigRepository, "set_config")
        assert hasattr(IConfigRepository, "delete_config")

        assert hasattr(IUsageRepository, "get_by_session_id")
        assert hasattr(IUsageRepository, "get_stats")
