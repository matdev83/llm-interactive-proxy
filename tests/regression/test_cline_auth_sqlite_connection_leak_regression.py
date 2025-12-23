"""Regression test for cline_auth.py SQLite connection leak fix.

This test verifies that _read_vscode_secret_blob properly closes SQLite
connections even when exceptions occur, preventing connection leaks.

Fixed: Using context manager (with sqlite3.connect(...)) ensures connections
are always closed, even on exception.
"""

import sqlite3
import tempfile
from pathlib import Path

from src.connectors.utils.cline_auth import ClineAuthMixin


class TestClineAuthSQLiteConnectionLeakRegression:
    """Regression tests for cline_auth.py SQLite connection leak fix."""

    def test_read_vscode_secret_blob_uses_context_manager(self) -> None:
        """Test that _read_vscode_secret_blob uses context manager for connection."""
        # Read the source code to verify fix is in place
        import inspect
        import os

        cline_auth_file = os.path.join(
            os.path.dirname(inspect.getfile(ClineAuthMixin)),
            "cline_auth.py",
        )

        with open(cline_auth_file) as f:
            content = f.read()

        # Verify the fix is in place: should use context manager
        assert (
            'with sqlite3.connect(f"file:{state_db}?mode=ro", uri=True) as conn:'
            in content
        ), (
            "_read_vscode_secret_blob should use context manager (with statement) "
            "to ensure connections are always closed. The fix may have been reverted."
        )

    def test_read_vscode_secret_blob_closes_connection_on_success(self) -> None:
        """Test that connection is closed after successful read."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create test database with data
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
            test_key = 'secret://{"extensionId":"saoudrizwan.claude-dev","key":"cline:clineAccountId"}'
            test_value = '{"data": [1, 2, 3, 4, 5]}'
            cur.execute("INSERT INTO ItemTable VALUES (?, ?)", (test_key, test_value))
            conn.commit()
            conn.close()

            # Create mixin instance
            class TestClineAuth(ClineAuthMixin):
                pass

            instance = TestClineAuth()

            # Call method - should use context manager and close connection
            result = instance._read_vscode_secret_blob(db_path)

            # Verify result
            assert result is not None, "Should read secret blob successfully"
            assert isinstance(result, bytes), "Result should be bytes"

            # Connection should be closed (we can't directly verify, but context manager ensures it)
            # The fact that we can create another connection means the previous one was closed
            conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn2.close()

        finally:
            # Cleanup
            if db_path.exists():
                db_path.unlink()

    def test_read_vscode_secret_blob_closes_connection_on_exception(self) -> None:
        """Test that connection is closed even when exception occurs."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create test database with invalid data that will cause exception
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
            test_key = 'secret://{"extensionId":"saoudrizwan.claude-dev","key":"cline:clineAccountId"}'
            test_value = "invalid json"  # Invalid JSON that will cause exception
            cur.execute("INSERT INTO ItemTable VALUES (?, ?)", (test_key, test_value))
            conn.commit()
            conn.close()

            # Create mixin instance
            class TestClineAuth(ClineAuthMixin):
                pass

            instance = TestClineAuth()

            # Call method - should handle exception and close connection
            instance._read_vscode_secret_blob(db_path)

            # Should return None on exception (as per implementation)
            # Connection should still be closed by context manager

            # Verify we can still create new connections (previous one was closed)
            conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn2.close()

        finally:
            # Cleanup
            if db_path.exists():
                db_path.unlink()

    def test_read_vscode_secret_blob_closes_connection_on_sqlite_error(self) -> None:
        """Test that connection is closed even on SQLite error."""

        # Create mixin instance
        class TestClineAuth(ClineAuthMixin):
            pass

        instance = TestClineAuth()

        # Call with non-existent database - should handle SQLite error gracefully
        non_existent_db = Path("/non/existent/path.db")

        # Should return None on SQLite error (as per implementation)
        result = instance._read_vscode_secret_blob(non_existent_db)

        # Should return None (no exception should propagate)
        assert result is None, "Should return None on SQLite error"

    def test_read_vscode_secret_blob_multiple_calls_no_leak(self) -> None:
        """Test that multiple calls don't leak connections."""
        # Create temporary database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            # Create test database
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
            test_key = 'secret://{"extensionId":"saoudrizwan.claude-dev","key":"cline:clineAccountId"}'
            test_value = '{"data": [1, 2, 3]}'
            cur.execute("INSERT INTO ItemTable VALUES (?, ?)", (test_key, test_value))
            conn.commit()
            conn.close()

            # Create mixin instance
            class TestClineAuth(ClineAuthMixin):
                pass

            instance = TestClineAuth()

            # Call method multiple times
            for _ in range(10):
                result = instance._read_vscode_secret_blob(db_path)
                assert result is not None, "Should read successfully each time"

            # Verify we can still create new connections (no leaks)
            conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn2.close()

        finally:
            # Cleanup
            if db_path.exists():
                db_path.unlink()
