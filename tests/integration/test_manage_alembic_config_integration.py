import importlib.util
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

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


# Cache loaded modules to avoid reloading on each test
_module_cache: dict[str, object] = {}

def load_script_module(script_path: Path):
    """Dynamically load the script as a module."""
    cache_key = str(script_path)
    if cache_key in _module_cache:
        return _module_cache[cache_key]
    
    spec = importlib.util.spec_from_file_location("manage_alembic_config", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _module_cache[cache_key] = module
    return module


def test_alembic_ini_exists_integration(temp_project_root: Path) -> None:
    """
    Test scenario: alembic.ini exists.
    The script should execute alembic without copying, and alembic.ini content should remain.
    """
    alembic_ini = temp_project_root / "alembic.ini"
    alembic_example_ini = temp_project_root / "alembic.example.ini"
    script_path = temp_project_root / "manage_alembic_config.py"

    # Setup: Create alembic.ini and alembic.example.ini
    initial_content = "script_location = initial_migrations"
    alembic_ini.write_text(initial_content)
    alembic_example_ini.write_text("script_location = example_migrations")

    module = load_script_module(script_path)

    # Mock subprocess.run to avoid actual execution
    with patch("subprocess.run") as mock_run, patch("sys.exit"):
        mock_run.return_value = MagicMock(returncode=0, stdout="alembic current", stderr="")
        
        # Execute the main function
        # We need to pass args via sys.argv or direct function call if available
        # The script calls manage_alembic_config(sys.argv[1:]) in if __name__ == "__main__"
        # We can call the function directly
        
        args = [f"--project-root={temp_project_root}", "current"]
        module.manage_alembic_config(args)

        # Assertions
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "alembic" in call_args
        assert "current" in call_args
        
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
    script_path = temp_project_root / "manage_alembic_config.py"

    # Setup: Remove alembic.ini, create alembic.example.ini
    if alembic_ini.exists():
        alembic_ini.unlink()
    example_content = "script_location = example_migrations"
    alembic_example_ini.write_text(example_content)

    module = load_script_module(script_path)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="alembic history", stderr="")

        # Execute the script
        args = [f"--project-root={temp_project_root}", "history"]
        module.manage_alembic_config(args)

        # Assertions
        assert alembic_ini.exists()
        assert alembic_ini.read_text() == example_content
        
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "alembic" in call_args
        assert "history" in call_args


def test_alembic_ini_and_example_missing_integration(temp_project_root: Path) -> None:
    """
    Test scenario: Both alembic.ini and alembic.example.ini are missing.
    The script should print an error and exit with a non-zero status.
    """
    alembic_ini = temp_project_root / "alembic.ini"
    alembic_example_ini = temp_project_root / "alembic.example.ini"
    script_path = temp_project_root / "manage_alembic_config.py"

    # Setup: Ensure both files are missing
    if alembic_ini.exists():
        alembic_ini.unlink()
    if alembic_example_ini.exists():
        alembic_example_ini.unlink()

    module = load_script_module(script_path)

    with patch("sys.exit") as mock_exit:
        # Execute the script
        args = [f"--project-root={temp_project_root}", "stamp", "head"]
        module.manage_alembic_config(args)

        # Assertions
        mock_exit.assert_called_with(1)

