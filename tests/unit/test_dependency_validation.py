"""
Test to validate that all dependencies declared in pyproject.toml are actually installed.

This test prevents issues where dependencies are declared but not installed,
which can cause runtime failures that aren't caught by other tests.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import tomli


class DependencyValidator:
    """Validates that all declared dependencies are properly installed."""

    def __init__(self, project_root: Path):
        """Initialize the validator with the project root path.

        Args:
            project_root: Path to the project root directory containing pyproject.toml
        """
        self.project_root = project_root
        self.pyproject_path = project_root / "pyproject.toml"

    def _load_pyproject_toml(self) -> dict[str, Any]:
        """Load and parse the pyproject.toml file.

        Returns:
            The parsed pyproject.toml content as a dictionary

        Raises:
            FileNotFoundError: If pyproject.toml doesn't exist
            tomli.TOMLDecodeError: If pyproject.toml is malformed
        """
        if not self.pyproject_path.exists():
            raise FileNotFoundError(
                f"pyproject.toml not found at {self.pyproject_path}"
            )

        with open(self.pyproject_path, "rb") as f:
            return tomli.load(f)

    def _extract_dependencies(self, pyproject_data: dict[str, Any]) -> list[str]:
        """Extract all dependencies from pyproject.toml.

        Args:
            pyproject_data: The parsed pyproject.toml content

        Returns:
            List of all dependency specifications (main + optional dev dependencies)
        """
        dependencies = []

        # Extract main dependencies
        project_deps = pyproject_data.get("project", {}).get("dependencies", [])
        dependencies.extend(project_deps)

        # Extract optional dependencies (like dev dependencies)
        optional_deps = pyproject_data.get("project", {}).get(
            "optional-dependencies", {}
        )
        for dep_group in optional_deps.values():
            dependencies.extend(dep_group)

        return dependencies

    def _normalize_package_name(self, dependency_spec: str) -> str:
        """Extract and normalize the package name from a dependency specification.

        Args:
            dependency_spec: A dependency specification like "requests>=2.0" or "fastapi[standard]"

        Returns:
            The normalized package name (e.g., "requests", "fastapi")
        """
        # Remove version constraints and extras
        # Examples: "requests>=2.0" -> "requests", "fastapi[standard]" -> "fastapi"
        package_name = re.split(r"[<>=!\[\s]", dependency_spec)[0].strip()

        # Normalize package name (replace underscores with hyphens, lowercase)
        return package_name.lower().replace("_", "-")

    def _get_import_name(self, package_name: str) -> str:
        """Get the import name for a package (which may differ from the package name).

        Args:
            package_name: The package name as it appears in pip

        Returns:
            The name to use for importing the package
        """
        # Common mappings where import name differs from package name
        name_mappings = {
            "python-dotenv": "dotenv",
            "pyyaml": "yaml",
            "pillow": "PIL",
            "beautifulsoup4": "bs4",
            "msgpack-python": "msgpack",
            "python-dateutil": "dateutil",
            "attrs": "attr",
            "pytz": "pytz",
            "six": "six",
            "setuptools": "setuptools",
            "wheel": "wheel",
            "pip": "pip",
            "google-auth": "google.auth",
            "google-auth-oauthlib": "google_auth_oauthlib",
            "google-genai": "google.genai",
            "json-repair": "json_repair",
            "pytest-asyncio": "pytest_asyncio",
            "pytest-cov": "pytest_cov",
            "pytest-httpx": "pytest_httpx",
            "pytest-mock": "pytest_mock",
            "pytest-snapshot": "pytest_snapshot",
            "types-pyyaml": "types_pyyaml",
            "dependency-injector": "dependency_injector",
            "llm-accounting": "llm_accounting",
        }

        return name_mappings.get(package_name, package_name.replace("-", "_"))

    def _is_package_installed(self, package_name: str) -> bool:
        """Check if a package is installed and importable.

        Args:
            package_name: The package name to check

        Returns:
            True if the package is installed and importable, False otherwise
        """
        import_name = self._get_import_name(package_name)

        try:
            # First try direct import
            importlib.import_module(import_name)
            return True
        except ImportError:
            pass

        # For packages with dots in import name, try importing the top-level module
        if "." in import_name:
            top_level = import_name.split(".")[0]
            try:
                importlib.import_module(top_level)
                return True
            except ImportError:
                pass

        # Try alternative import strategies for complex packages
        try:
            # Check if it's available via importlib.util
            spec = importlib.util.find_spec(import_name)
            if spec is not None:
                return True
        except (ImportError, ModuleNotFoundError, ValueError):
            pass

        # As a last resort, check with pip list
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=freeze"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                installed_packages = result.stdout.lower()
                # Check both the original name and normalized name
                normalized_name = package_name.replace("-", "_")
                return (
                    f"{package_name}==" in installed_packages
                    or f"{normalized_name}==" in installed_packages
                )
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass

        return False

    def validate_dependencies(self) -> tuple[list[str], list[str]]:
        """Validate all dependencies from pyproject.toml.

        Returns:
            A tuple of (installed_dependencies, missing_dependencies)
        """
        pyproject_data = self._load_pyproject_toml()
        dependencies = self._extract_dependencies(pyproject_data)

        installed = []
        missing = []

        for dep_spec in dependencies:
            package_name = self._normalize_package_name(dep_spec)

            if self._is_package_installed(package_name):
                installed.append(dep_spec)
            else:
                missing.append(dep_spec)

        return installed, missing


class TestDependencyValidation:
    """Test class for dependency validation."""

    @pytest.fixture(scope="session")
    def validator(self) -> DependencyValidator:
        """Create a dependency validator for the project."""
        project_root = Path(__file__).parent.parent.parent
        return DependencyValidator(project_root)

    def test_all_dependencies_are_installed(
        self, validator: DependencyValidator
    ) -> None:
        """
        Test that all dependencies declared in pyproject.toml are actually installed.

        This test prevents runtime failures caused by missing dependencies that
        aren't caught by other tests due to lazy loading or isolated test contexts.

        The test will:
        1. Parse pyproject.toml to extract all dependencies (main + optional)
        2. Check if each dependency is installed and importable
        3. Fail with an informative message listing any missing dependencies
        """
        installed, missing = validator.validate_dependencies()

        # Create informative error message if any dependencies are missing
        if missing:
            missing_list = "\n  - ".join(missing)
            total_deps = len(installed) + len(missing)

            error_msg = (
                f"Missing dependencies detected!\n\n"
                f"Found {len(missing)} missing dependencies out of {total_deps} total:\n"
                f"  - {missing_list}\n\n"
                f"To fix this issue, run:\n"
                f"  ./.venv/Scripts/python.exe -m pip install -e .[dev]\n\n"
                f"This test prevents runtime failures where dependencies are declared "
                f"in pyproject.toml but not actually installed, which can cause server "
                f"startup failures that aren't caught by isolated unit tests."
            )
            pytest.fail(error_msg)

        # If we get here, all dependencies are installed
        assert len(missing) == 0, "All dependencies should be installed"
        assert len(installed) > 0, "Should have found some installed dependencies"

    def test_pyproject_toml_exists_and_is_valid(
        self, validator: DependencyValidator
    ) -> None:
        """Test that pyproject.toml exists and can be parsed."""
        # This should not raise an exception
        pyproject_data = validator._load_pyproject_toml()

        # Basic validation that it has the expected structure
        assert (
            "project" in pyproject_data
        ), "pyproject.toml should have a [project] section"
        assert (
            "dependencies" in pyproject_data["project"]
        ), "Should have dependencies section"

        dependencies = pyproject_data["project"]["dependencies"]
        assert isinstance(dependencies, list), "Dependencies should be a list"
        assert len(dependencies) > 0, "Should have at least some dependencies"

    def test_dependency_parsing_logic(self, validator: DependencyValidator) -> None:
        """Test the dependency parsing and normalization logic."""
        # Test package name normalization
        assert validator._normalize_package_name("requests>=2.0") == "requests"
        assert validator._normalize_package_name("fastapi[standard]") == "fastapi"
        assert validator._normalize_package_name("python-dotenv") == "python-dotenv"
        assert validator._normalize_package_name("PyYAML>=6.0") == "pyyaml"

        # Test import name mapping
        assert validator._get_import_name("python-dotenv") == "dotenv"
        assert validator._get_import_name("pyyaml") == "yaml"
        assert validator._get_import_name("json-repair") == "json_repair"
        assert validator._get_import_name("google-auth") == "google.auth"
        assert validator._get_import_name("requests") == "requests"  # No mapping needed
