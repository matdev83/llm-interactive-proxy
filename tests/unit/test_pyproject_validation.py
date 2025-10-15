"""Validation checks for the repository's ``pyproject.toml`` file.

These tests load and inspect the real configuration so that failures in the
project metadata surface during CI. A previous version defined helper classes
inside the test suite and stubbed out their behaviour, meaning the tests would
pass even if dependencies were missing or the configuration was malformed.
"""

from __future__ import annotations

from pathlib import Path

import tomli

PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _load_pyproject() -> dict[str, object]:
    with PYPROJECT_PATH.open("rb") as handle:
        return tomli.load(handle)


def test_pyproject_toml_exists() -> None:
    assert PYPROJECT_PATH.exists(), f"pyproject.toml not found at {PYPROJECT_PATH}"


def test_pyproject_toml_is_readable() -> None:
    assert PYPROJECT_PATH.is_file(), f"pyproject.toml is not a file: {PYPROJECT_PATH}"


def test_pyproject_toml_parses() -> None:
    data = _load_pyproject()
    assert isinstance(data, dict)


def test_project_section_has_required_fields() -> None:
    data = _load_pyproject()
    project = data.get("project")
    assert isinstance(project, dict), "[project] section missing or invalid"

    required_fields = [
        "name",
        "version",
        "description",
        "authors",
        "requires-python",
        "dependencies",
    ]

    for field in required_fields:
        assert field in project, f"Missing required field in [project]: {field}"


def test_project_dependencies_are_non_empty_strings() -> None:
    data = _load_pyproject()
    project = data.get("project")
    assert isinstance(project, dict)

    dependencies = project.get("dependencies")
    assert isinstance(dependencies, list), "project.dependencies must be a list"
    assert dependencies, "project.dependencies should not be empty"

    for dependency in dependencies:
        assert isinstance(dependency, str), "Dependencies must be strings"
        assert dependency.strip(), "Dependency entries must not be blank"


def test_optional_dependencies_are_lists_of_strings() -> None:
    data = _load_pyproject()
    project = data.get("project")
    assert isinstance(project, dict)

    optional = project.get("optional-dependencies", {})
    assert isinstance(optional, dict), "project.optional-dependencies must be a mapping"

    for group, deps in optional.items():
        assert isinstance(deps, list), f"Dependency group '{group}' must be a list"
        assert deps, f"Dependency group '{group}' must not be empty"
        for dep in deps:
            assert isinstance(dep, str), "Dependency entries must be strings"
            assert dep.strip(), "Dependency entries must not be blank"


def test_build_system_requires_setuptools() -> None:
    data = _load_pyproject()
    build_system = data.get("build-system")
    assert isinstance(build_system, dict), "[build-system] section missing or invalid"

    requires = build_system.get("requires")
    assert isinstance(requires, list), "build-system.requires must be a list"
    assert any("setuptools" in requirement for requirement in requires)
