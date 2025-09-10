"""Tests for pyproject.toml validation and dependency installation status."""

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import tomli


class PyProjectTOMLValidator:
    """Validator for pyproject.toml file syntax and structure."""

    def __init__(self, pyproject_path: Path):
        """Initialize validator with path to pyproject.toml.

        Args:
            pyproject_path: Path to the pyproject.toml file
        """
        self.pyproject_path = pyproject_path
        self._parsed_content: dict[str, Any] | None = None
        self._validation_errors: list[str] = []

    def validate_syntax(self) -> bool:
        """Validate TOML syntax by attempting to parse the file.

        Returns:
            bool: True if syntax is valid, False otherwise
        """
        try:
            with open(self.pyproject_path, "rb") as f:
                self._parsed_content = tomli.load(f)
            return True
        except Exception as e:
            self._validation_errors.append(f"TOML syntax error: {e}")
            return False
        except FileNotFoundError:
            self._validation_errors.append(f"File not found: {self.pyproject_path}")
            return False

    def validate_structure(self) -> bool:
        """Validate that required sections and fields are present.

        Returns:
            bool: True if structure is valid, False otherwise
        """
        if self._parsed_content is None and not self.validate_syntax():
            return False

        # At this point, _parsed_content should be set by validate_syntax()
        assert (
            self._parsed_content is not None
        ), "Content should be parsed after validate_syntax()"
        content = self._parsed_content
        is_valid = True

        # Check for required top-level sections
        required_sections = ["project", "build-system"]
        for section in required_sections:
            if section not in content:
                self._validation_errors.append(f"Missing required section: [{section}]")
                is_valid = False

        # Validate project section
        if "project" in content:
            project = content["project"]
            required_project_fields = [
                "name",
                "version",
                "description",
                "authors",
                "requires-python",
            ]

            for field in required_project_fields:
                if field not in project:
                    self._validation_errors.append(
                        f"Missing required field in [project]: {field}"
                    )
                    is_valid = False

            # Validate authors format
            if "authors" in project and not isinstance(project["authors"], list):
                self._validation_errors.append("project.authors must be a list")
                is_valid = False

            # Validate optional-dependencies structure
            if "optional-dependencies" in project:
                optional_deps = project["optional-dependencies"]
                if not isinstance(optional_deps, dict):
                    self._validation_errors.append(
                        "project.optional-dependencies must be a dictionary"
                    )
                    is_valid = False
                else:
                    # Check that each dependency group is a list
                    for group_name, deps in optional_deps.items():
                        if not isinstance(deps, list):
                            self._validation_errors.append(
                                f"project.optional-dependencies.{group_name} must be a list"
                            )
                            is_valid = False

        # Validate build-system section
        if "build-system" in content:
            build_system = content["build-system"]
            if "requires" not in build_system:
                self._validation_errors.append("Missing build-system.requires")
                is_valid = False
            elif not isinstance(build_system["requires"], list):
                self._validation_errors.append("build-system.requires must be a list")
                is_valid = False

        return is_valid

    def get_validation_errors(self) -> list[str]:
        """Get list of validation errors.

        Returns:
            List of validation error messages
        """
        return self._validation_errors.copy()

    def get_parsed_content(self) -> dict[str, Any] | None:
        """Get the parsed TOML content.

        Returns:
            Parsed TOML content as dictionary, or None if parsing failed
        """
        return self._parsed_content


class DependencyChecker:
    """Checker for dependency installation status."""

    # Class-level cache to share installed packages across instances
    _installed_packages_cache: dict[str, set[str]] = {}
    _cache_timestamps: dict[str, float] = {}

    def __init__(self, pyproject_path: Path, venv_path: Path):
        """Initialize dependency checker.

        Args:
            pyproject_path: Path to pyproject.toml
            venv_path: Path to virtual environment
        """
        self.pyproject_path = pyproject_path
        self.venv_path = venv_path
        self._cache_file = pyproject_path.parent / ".dependency_check_cache"
        self._pyproject_mtime = (
            pyproject_path.stat().st_mtime if pyproject_path.exists() else 0
        )
        # Create a cache key based on venv path
        self._cache_key = str(venv_path)

    def _get_cache_key(self) -> str:
        """Generate cache key based on pyproject.toml modification time."""
        return f"{self._pyproject_mtime}"

    def _is_cache_valid(self) -> bool:
        """Check if cache is valid (pyproject.toml hasn't changed)."""
        if not self._cache_file.exists():
            return False

        try:
            with open(self._cache_file) as f:
                cached_mtime = float(f.read().strip())
            return cached_mtime == self._pyproject_mtime
        except (ValueError, OSError):
            return False

    def _save_cache(self) -> None:
        """Save current cache state."""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_file, "w") as f:
                f.write(str(self._pyproject_mtime))
        except OSError:
            # Ignore cache write errors
            pass

    def _get_installed_packages(self) -> set[str]:
        """Get set of installed package names using importlib.metadata.

        Returns:
            Set of installed package names (normalized to lowercase)
        """
        # Check if we have a valid cache for this venv
        current_time = self._pyproject_mtime
        if (
            self._cache_key in self._installed_packages_cache
            and self._cache_key in self._cache_timestamps
            and self._cache_timestamps[self._cache_key] >= current_time
        ):
            return self._installed_packages_cache[self._cache_key]

        try:
            # Try to use importlib.metadata first (faster)
            try:
                import importlib.metadata

                installed = {
                    dist.metadata["Name"].lower()
                    for dist in importlib.metadata.distributions()
                }
            except ImportError:
                # Fallback to subprocess method for older Python versions
                pip_exe = self.venv_path / "Scripts" / "python.exe"
                if not pip_exe.exists():
                    # Try Linux/macOS path
                    pip_exe = self.venv_path / "bin" / "python"

                if not pip_exe.exists():
                    raise FileNotFoundError(
                        f"Python executable not found in venv: {pip_exe}"
                    )

                # Use pip show to get installed packages with a shorter timeout
                result = subprocess.run(
                    [str(pip_exe), "-m", "pip", "list", "--format=freeze"],
                    capture_output=True,
                    text=True,
                    timeout=15,  # Reduced timeout
                )

                if result.returncode != 0:
                    raise subprocess.SubprocessError(
                        f"pip list failed: {result.stderr}"
                    )

                installed = set()
                for line in result.stdout.strip().split("\n"):
                    if "==" in line:
                        package_name = line.split("==")[0].lower()
                        installed.add(package_name)

            # Cache the result
            self._installed_packages_cache[self._cache_key] = installed
            self._cache_timestamps[self._cache_key] = current_time
            return installed

        except (
            subprocess.TimeoutExpired,
            subprocess.SubprocessError,
            FileNotFoundError,
        ) as e:
            pytest.fail(f"Failed to get installed packages: {e}")

    def _extract_dependencies_from_pyproject(self) -> set[str]:
        """Extract dependency names from pyproject.toml.

        Returns:
            Set of dependency package names (normalized to lowercase)
        """
        try:
            with open(self.pyproject_path, "rb") as f:
                content = tomli.load(f)
        except Exception as e:
            pytest.fail(f"Failed to parse pyproject.toml: {e}")

        dependencies = set()

        # Extract main dependencies
        if "project" in content and "dependencies" in content["project"]:
            for dep in content["project"]["dependencies"]:
                # Extract package name (before any version specifiers)
                package_name = (
                    dep.split()[0]
                    .split(">=")[0]
                    .split("==")[0]
                    .split("<=")[0]
                    .split("!=")[0]
                    .split(";")[0]
                    .strip()
                )
                # Handle extras syntax like package[extra]
                if "[" in package_name and "]" in package_name:
                    package_name = package_name.split("[")[0]
                dependencies.add(package_name.lower())

        # Extract optional dependencies
        if "project" in content and "optional-dependencies" in content["project"]:
            for group_deps in content["project"]["optional-dependencies"].values():
                for dep in group_deps:
                    package_name = (
                        dep.split()[0]
                        .split(">=")[0]
                        .split("==")[0]
                        .split("<=")[0]
                        .split("!=")[0]
                        .split(";")[0]
                        .strip()
                    )
                    # Handle extras syntax like package[extra]
                    if "[" in package_name and "]" in package_name:
                        package_name = package_name.split("[")[0]
                    dependencies.add(package_name.lower())

        return dependencies

    def check_dependencies_installed(self, force_check: bool = False) -> bool:
        """Check if all dependencies from pyproject.toml are installed.

        Args:
            force_check: If True, ignore cache and always check

        Returns:
            True if all dependencies are installed, False otherwise
        """
        # Check cache first (unless force_check is True)
        if not force_check and self._is_cache_valid():
            return True

        required_deps = self._extract_dependencies_from_pyproject()
        installed_packages = self._get_installed_packages()

        missing_deps = required_deps - installed_packages

        if missing_deps:
            pytest.fail(
                f"Missing dependencies: {', '.join(sorted(missing_deps))}. "
                f"Run: ./.venv/Scripts/python.exe -m pip install -e .[dev]"
            )

        # Save cache if check passed
        self._save_cache()
        return True


@pytest.fixture
def pyproject_path() -> Path:
    """Get path to pyproject.toml file."""
    return Path(__file__).parent.parent.parent / "pyproject.toml"


@pytest.fixture
def venv_path() -> Path:
    """Get path to virtual environment."""
    return Path(__file__).parent.parent.parent / ".venv"


def test_pyproject_toml_syntax_validation(pyproject_path: Path) -> None:
    """Test that pyproject.toml has valid TOML syntax."""
    validator = PyProjectTOMLValidator(pyproject_path)
    is_valid = validator.validate_syntax()

    if not is_valid:
        errors = validator.get_validation_errors()
        pytest.fail("pyproject.toml syntax validation failed:\n" + "\n".join(errors))


def test_pyproject_toml_structure_validation(pyproject_path: Path) -> None:
    """Test that pyproject.toml has required structure and fields."""
    validator = PyProjectTOMLValidator(pyproject_path)
    is_valid = validator.validate_structure()

    if not is_valid:
        errors = validator.get_validation_errors()
        pytest.fail("pyproject.toml structure validation failed:\n" + "\n".join(errors))


def test_pyproject_toml_complete_validation(pyproject_path: Path) -> None:
    """Test complete validation of pyproject.toml (syntax + structure)."""
    validator = PyProjectTOMLValidator(pyproject_path)

    syntax_valid = validator.validate_syntax()
    structure_valid = validator.validate_structure()

    if not syntax_valid or not structure_valid:
        all_errors = validator.get_validation_errors()
        pytest.fail("pyproject.toml validation failed:\n" + "\n".join(all_errors))


def test_dependency_installation_status(pyproject_path: Path, venv_path: Path) -> None:
    """Test that all dependencies from pyproject.toml are actually installed."""
    if not venv_path.exists():
        pytest.skip("Virtual environment not found, skipping dependency check")

    checker = DependencyChecker(pyproject_path, venv_path)
    checker.check_dependencies_installed()


def test_dependency_installation_status_forced(
    pyproject_path: Path, venv_path: Path
) -> None:
    """Test dependency installation status with cache bypass."""
    if not venv_path.exists():
        pytest.skip("Virtual environment not found, skipping dependency check")

    checker = DependencyChecker(pyproject_path, venv_path)
    checker.check_dependencies_installed(force_check=True)


def test_pyproject_toml_exists(pyproject_path: Path) -> None:
    """Test that pyproject.toml file exists."""
    assert pyproject_path.exists(), f"pyproject.toml not found at {pyproject_path}"


def test_pyproject_toml_is_readable(pyproject_path: Path) -> None:
    """Test that pyproject.toml file is readable."""
    assert pyproject_path.is_file(), f"pyproject.toml is not a file: {pyproject_path}"
    assert os.access(
        pyproject_path, os.R_OK
    ), f"pyproject.toml is not readable: {pyproject_path}"


def test_build_system_requires_setuptools(pyproject_path: Path) -> None:
    """Test that build-system requires setuptools."""
    validator = PyProjectTOMLValidator(pyproject_path)
    validator.validate_syntax()
    content = validator.get_parsed_content()

    assert content is not None, "Failed to parse pyproject.toml"
    assert "build-system" in content, "Missing build-system section"
    assert "requires" in content["build-system"], "Missing build-system.requires"

    requires = content["build-system"]["requires"]
    assert isinstance(requires, list), "build-system.requires must be a list"
    assert any(
        "setuptools" in req for req in requires
    ), "setuptools must be in build-system.requires"
