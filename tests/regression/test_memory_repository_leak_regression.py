"""Regression test for MemoryRepository SQLite connection leak fix.

This test verifies that MemoryRepository properly closes SQLite connections
when close() is called, preventing connection leaks.
"""

import pytest
import tempfile
import os
from pathlib import Path

from src.core.memory.config import MemoryConfiguration
from src.core.memory.sqlite_repository import MemoryRepository


class TestMemoryRepositoryLeakRegression:
    """Regression tests for MemoryRepository SQLite connection leak fix."""

    @pytest.mark.asyncio
    async def test_close_method_exists(self) -> None:
        """Test that MemoryRepository has a close() method."""
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            config = MemoryConfiguration(database_path=temp_db.name)
            repo = MemoryRepository(config)

            assert hasattr(repo, "close"), (
                "MemoryRepository should have a close() method to prevent connection leaks."
            )
            assert callable(repo.close), "close() should be callable."
        finally:
            if os.path.exists(temp_db.name):
                os.unlink(temp_db.name)

    @pytest.mark.asyncio
    async def test_close_closes_database_connection(self) -> None:
        """Test that close() properly closes the database connection."""
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            config = MemoryConfiguration(database_path=temp_db.name)
            repo = MemoryRepository(config)

            # Initialize schema (this opens the connection)
            await repo.initialize_schema()

            # Verify connection is open
            assert repo._db is not None, "Database connection should be open after initialize_schema()"

            # Close the repository
            await repo.close()

            # Verify connection is closed (set to None)
            assert repo._db is None, (
                "Database connection (_db) should be None after close(). "
                "This prevents connection leaks."
            )
        finally:
            if os.path.exists(temp_db.name):
                os.unlink(temp_db.name)

    @pytest.mark.asyncio
    async def test_multiple_repositories_close_properly(self) -> None:
        """Test that multiple repositories can be closed without leaks."""
        repositories = []
        temp_files = []

        try:
            # Create multiple repositories
            for i in range(3):
                temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
                temp_db.close()
                temp_files.append(temp_db.name)

                config = MemoryConfiguration(database_path=temp_db.name)
                repo = MemoryRepository(config)
                await repo.initialize_schema()
                repositories.append(repo)

            # Verify all have open connections
            for repo in repositories:
                assert repo._db is not None

            # Close all repositories
            for repo in repositories:
                await repo.close()

            # Verify all connections are closed
            closed_count = sum(1 for repo in repositories if repo._db is None)
            assert closed_count == len(repositories), (
                f"Expected all {len(repositories)} repositories to be closed, "
                f"but only {closed_count} were closed. Connection leak detected."
            )
        finally:
            # Cleanup temp files
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    try:
                        os.unlink(temp_file)
                    except Exception:
                        pass

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        """Test that calling close() multiple times is safe."""
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            config = MemoryConfiguration(database_path=temp_db.name)
            repo = MemoryRepository(config)
            await repo.initialize_schema()

            # Close first time
            await repo.close()
            assert repo._db is None

            # Close again - should not raise an error
            await repo.close()
            assert repo._db is None
        finally:
            if os.path.exists(temp_db.name):
                os.unlink(temp_db.name)

    @pytest.mark.asyncio
    async def test_close_without_initialization(self) -> None:
        """Test that close() works even if repository was never initialized."""
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()

        try:
            config = MemoryConfiguration(database_path=temp_db.name)
            repo = MemoryRepository(config)

            # Close without initializing - should not raise an error
            await repo.close()
            assert repo._db is None
        finally:
            if os.path.exists(temp_db.name):
                os.unlink(temp_db.name)
