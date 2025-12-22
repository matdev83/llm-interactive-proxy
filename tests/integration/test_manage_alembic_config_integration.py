import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Creates a temporary project root for testing."""
    # Ensure a dummy venv python is present as the script uses sys.executable
    venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("fake python executable")

    # Copy the manage_alembic_config.py script into the temporary root
    shutil.copy(
        Path(__file__).resolve().parents[2]
        / "dev"
        / "scripts"
        / "manage_alembic_config.py",
        tmp_path / "manage_alembic_config.py",
    )

    return tmp_path


def test_alembic_ini_exists_integration(temp_project_root: Path) -> None:
    """
    Test scenario: alembic.ini exists.
    The script should execute alembic without copying, and alembic.ini content should remain.
    """
    alembic_ini = temp_project_root / "alembic.ini"
    alembic_example_ini = temp_project_root / "alembic.example.ini"
    script_to_run = temp_project_root / "manage_alembic_config.py"

    # Setup: Create alembic.ini and alembic.example.ini
    initial_content = "script_location = initial_migrations"
    alembic_ini.write_text(initial_content)
    alembic_example_ini.write_text("script_location = example_migrations")

    # Execute the script using a real subprocess call
    result = subprocess.run(
        [
            sys.executable,
            str(script_to_run),
            f"--project-root={temp_project_root}",
            "current",
        ],
        cwd=temp_project_root,  # Run in temp_project_root so paths resolve correctly
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )

    # Assertions
    # The internal 'alembic' command is expected to fail as the environment is not fully set up.
    # The script itself should return a non-zero exit code due to this.
    assert result.returncode != 0
    assert "Executing command" in result.stdout
    assert (
        "alembic current" in result.stdout
    )  # Check if alembic command was passed in print output
    assert (
        "ERROR: Alembic command failed" in result.stdout
    )  # The script should report an error
    assert (
        ", line: 1" in result.stdout
    )  # Indicates a parsing error from alembic.ini at line 1

    assert alembic_ini.read_text() == initial_content  # alembic.ini should be unchanged


def test_alembic_ini_missing_example_exists_integration(
    temp_project_root: Path,
) -> None:
    """
    Test scenario: alembic.ini is missing, but alembic.example.ini exists.
    The script should copy from alembic.example.ini and then execute alembic.
    """
    alembic_ini = temp_project_root / "alembic.ini"
    alembic_example_ini = temp_project_root / "alembic.example.ini"
    script_to_run = (
        temp_project_root / "manage_alembic_config.py"
    )  # Adjusted to point to the copied script

    # Setup: Remove alembic.ini, create alembic.example.ini
    if alembic_ini.exists():
        alembic_ini.unlink()
    example_content = "script_location = example_migrations"
    alembic_example_ini.write_text(example_content)

    # Execute the script
    result = subprocess.run(
        [
            sys.executable,
            str(script_to_run),
            f"--project-root={temp_project_root}",
            "history",
        ],
        cwd=temp_project_root,
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )

    # Assertions
    assert result.returncode != 0  # Internal alembic command should fail
    assert (
        "INFO: alembic.ini not found. Copying from" in result.stdout
    )  # INFO message is now captured
    assert "Executing command" in result.stdout
    assert (
        "alembic history" in result.stdout
    )  # Check if alembic command was passed in print output
    assert (
        "ERROR: Alembic command failed" in result.stdout
    )  # The script should report an error
    assert (
        ", line: 1" in result.stdout
    )  # Indicates a parsing error from alembic.ini at line 1


def test_alembic_ini_and_example_missing_integration(temp_project_root: Path) -> None:
    """
    Test scenario: Both alembic.ini and alembic.example.ini are missing.
    The script should print an error and exit with a non-zero status.
    """
    alembic_ini = temp_project_root / "alembic.ini"
    alembic_example_ini = temp_project_root / "alembic.example.ini"
    script_to_run = temp_project_root / "manage_alembic_config.py"

    # Setup: Ensure both files are missing
    if alembic_ini.exists():
        alembic_ini.unlink()
    if alembic_example_ini.exists():
        alembic_example_ini.unlink()

    # Execute the script
    result = subprocess.run(
        [
            sys.executable,
            str(script_to_run),
            f"--project-root={temp_project_root}",
            "stamp",
            "head",
        ],
        cwd=temp_project_root,
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )

    # Assertions
    assert result.returncode != 0  # Should exit with an error
    assert "ERROR: Alembic configuration files missing. Expected:" in result.stdout
    assert (
        "Please create an alembic.ini file or provide an alembic.example.ini template."
        in result.stdout
    )
