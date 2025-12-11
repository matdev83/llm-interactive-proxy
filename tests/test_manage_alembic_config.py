import os
import shutil
import sys
import argparse
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Adjust the path to import the script directly for testing
sys.path.append(str(Path(__file__).resolve().parents[1] / "scripts"))
from manage_alembic_config import manage_alembic_config

@pytest.fixture
def temp_project_root(tmp_path: Path) -> Path:
    """Creates a temporary project root with necessary files."""
    # Create a dummy .venv/Scripts/python.exe
    venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("fake python executable")

    # Create dummy alembic.ini and alembic.example.ini content
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = migrations")
    (tmp_path / "alembic.example.ini").write_text("[alembic]\nscript_location = example_migrations")

    # This is the actual project root for the test scenario
    real_project_root = tmp_path

    # Mock Path(__file__).resolve().parents[1]
    # We need to simulate the Path object for the script itself (manage_alembic_config.py)
    mock_script_path = MagicMock(spec=Path)
    mock_script_path.resolve.return_value = MagicMock(spec=Path)
    # The parents attribute needs to behave like a tuple/list of Path objects
    mock_script_path.resolve.return_value.parents = (
        real_project_root / "scripts", # parents[0]
        real_project_root,             # parents[1] - this is what the script accesses
    )

    # Patch Path inside the manage_alembic_config module
    # The script calls `Path(__file__)` - so we need to mock the result of that.
    with patch("manage_alembic_config.Path", return_value=mock_script_path):
        yield real_project_root


@patch("subprocess.run")
@patch("shutil.copy")
def test_alembic_ini_exists(
    mock_copy: MagicMock, mock_subprocess_run: MagicMock, temp_project_root: Path
) -> None:
    """Test when alembic.ini already exists."""
    # Ensure alembic.ini exists
    (temp_project_root / "alembic.ini").write_text("existing alembic.ini")
    
    # Mock subprocess.run to return a successful result
    mock_subprocess_run.return_value = MagicMock(returncode=0)

    # Mock sys.executable to point to the dummy venv python
    with patch.object(sys, "executable", str(temp_project_root / ".venv" / "Scripts" / "python.exe")):
        manage_alembic_config(["upgrade", "head"])

    mock_copy.assert_not_called()
    
    expected_cmd = [str(temp_project_root / ".venv" / "Scripts" / "python.exe"), "-m", "alembic", "upgrade", "head"]
    mock_subprocess_run.assert_called_once_with(expected_cmd, env=os.environ.copy(), check=False)


@patch("subprocess.run")
@patch("shutil.copy")
def test_alembic_ini_missing_example_exists(
    mock_copy: MagicMock, mock_subprocess_run: MagicMock, temp_project_root: Path
) -> None:
    """Test when alembic.ini is missing, but alembic.example.ini exists."""
    # Remove alembic.ini
    (temp_project_root / "alembic.ini").unlink()

    # Ensure alembic.example.ini exists
    (temp_project_root / "alembic.example.ini").write_text("example alembic.ini content")

    # Mock subprocess.run to return a successful result
    mock_subprocess_run.return_value = MagicMock(returncode=0)

    with patch.object(sys, "executable", str(temp_project_root / ".venv" / "Scripts" / "python.exe")):
        manage_alembic_config(["revision", "--autogenerate", "-m", "initial commit"])

    mock_copy.assert_called_once_with(
        temp_project_root / "alembic.example.ini", temp_project_root / "alembic.ini"
    )
    assert (temp_project_root / "alembic.ini").exists()
    
    expected_cmd = [
        str(temp_project_root / ".venv" / "Scripts" / "python.exe"),
        "-m",
        "alembic",
        "revision",
        "--autogenerate",
        "-m",
        "initial commit",
    ]
    mock_subprocess_run.assert_called_once_with(expected_cmd, env=os.environ.copy(), check=False)


@patch("subprocess.run")
@patch("shutil.copy")
def test_alembic_ini_and_example_missing(
    mock_copy: MagicMock, mock_subprocess_run: MagicMock, temp_project_root: Path
) -> None:
    """Test when both alembic.ini and alembic.example.ini are missing."""
    # Remove both files
    (temp_project_root / "alembic.ini").unlink()
    (temp_project_root / "alembic.example.ini").unlink()

    # Mock subprocess.run to return a successful result (though it shouldn't be called)
    mock_subprocess_run.return_value = MagicMock(returncode=0)

    with pytest.raises(SystemExit) as excinfo:
        with patch.object(sys, "executable", str(temp_project_root / ".venv" / "Scripts" / "python.exe")):
            manage_alembic_config(["history"])

    assert excinfo.value.code == 1
    mock_copy.assert_not_called()
    mock_subprocess_run.assert_not_called()

