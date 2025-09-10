"""
Test to validate that mypy type checking passes on the src directory.

This test ensures that all source code passes mypy type checking,
which is important for maintaining code quality and catching type-related
bugs early.
"""

import subprocess
import sys
from pathlib import Path

import pytest


class TestMypyValidation:
    """Test class for mypy validation of source code."""

    def test_mypy_passes_on_src(self) -> None:
        """
        Test that mypy type checking passes on the src directory.

        This test runs mypy on the src directory and fails if any
        type checking errors are detected. This helps ensure code
        quality and catches type-related issues early.

        The test uses the project's mypy.ini configuration file
        to ensure consistent type checking behavior.

        """
        # Get the path to the src directory
        src_path = Path(__file__).parent.parent.parent / "src"

        # Ensure src directory exists
        assert src_path.exists(), f"Source directory not found at {src_path}"
        assert src_path.is_dir(), f"Source path {src_path} is not a directory"

        # Get the path to the Python executable in the virtual environment
        python_exe = Path(sys.executable)

        # Run mypy on the src directory
        try:
            result = subprocess.run(
                [str(python_exe), "-m", "mypy", str(src_path)],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                cwd=Path(__file__).parent.parent.parent,  # Project root
            )
        except subprocess.TimeoutExpired:
            pytest.fail("mypy validation timed out after 5 minutes")

        # Check if mypy found any errors
        if result.returncode != 0:
            # mypy found errors, create a detailed failure message
            error_msg = (
                f"mypy type checking failed on src directory!\n\n"
                f"Exit code: {result.returncode}\n\n"
                f"STDOUT:\n{result.stdout}\n\n"
                f"STDERR:\n{result.stderr}\n\n"
                f"This indicates there are type checking errors in the source code.\n"
                f"Please run 'mypy src' locally to see the specific errors and fix them."
            )

            pytest.fail(error_msg)

        # mypy passed successfully
        # The result might still contain some output (like notes/warnings)
        # but as long as the return code is 0, we consider it passed
        assert (
            result.returncode == 0
        ), f"mypy failed with unexpected return code: {result.returncode}"

    def test_mypy_config_exists(self) -> None:
        """
        Test that mypy configuration file exists.

        This ensures that the mypy validation is using the correct
        configuration for the project.
        """
        mypy_config_path = Path(__file__).parent.parent.parent / "mypy.ini"

        assert mypy_config_path.exists(), f"mypy.ini not found at {mypy_config_path}"
        assert (
            mypy_config_path.is_file()
        ), f"mypy.ini at {mypy_config_path} is not a file"

        # Verify it's not empty
        content = mypy_config_path.read_text()
        assert len(content.strip()) > 0, "mypy.ini appears to be empty"
