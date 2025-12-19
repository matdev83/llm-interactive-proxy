"""Architectural tests to enforce layer boundaries in hybrid_backend package.

Requirements satisfied:
- Req 5.4: When a layer violation occurs, the architecture check shall fail
"""

import ast
from pathlib import Path

import pytest

# Layer definitions (top to bottom)
LAYERS = {
    "facade": ["src/connectors/hybrid.py"],
    "orchestration": ["src/connectors/hybrid_backend/orchestration/"],
    "services": ["src/connectors/hybrid_backend/services/"],
    "infrastructure": ["src/connectors/hybrid_backend/infrastructure/"],
    "models": ["src/connectors/hybrid_backend/models/"],
}

# Allowed import directions (layer can import from layers below it)
ALLOWED_IMPORTS = {
    "facade": ["orchestration", "services", "infrastructure", "models"],
    "orchestration": ["services", "infrastructure", "models"],
    "services": ["infrastructure", "models"],
    "infrastructure": ["models"],
    "models": [],  # Models can only import stdlib/typing
}


def get_layer_for_path(path: str) -> str | None:
    """Determine which layer a file belongs to."""
    for layer, patterns in LAYERS.items():
        for pattern in patterns:
            if pattern in path:
                return layer
    return None


def extract_imports(file_path: Path) -> list[str]:
    """Extract all import statements from a Python file."""
    try:
        with open(file_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except SyntaxError:
        # Skip files with syntax errors (they'll be caught by other tests)
        return []

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def get_imported_layer(import_path: str) -> str | None:
    """Determine which layer an import belongs to."""
    for layer, patterns in LAYERS.items():
        for pattern in patterns:
            # Convert path pattern to import pattern
            import_pattern = pattern.replace("/", ".").rstrip("/")
            if import_pattern in import_path:
                return layer
    return None


@pytest.mark.unit
def test_no_upward_layer_imports():
    """Verify no module imports from a layer above it."""
    hybrid_backend = Path("src/connectors/hybrid_backend")
    hybrid_py = Path("src/connectors/hybrid.py")
    violations = []

    # Check hybrid_backend package
    for py_file in hybrid_backend.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        file_layer = get_layer_for_path(str(py_file))
        if not file_layer:
            continue

        for import_path in extract_imports(py_file):
            imported_layer = get_imported_layer(import_path)
            if imported_layer and imported_layer != file_layer:
                allowed = ALLOWED_IMPORTS.get(file_layer, [])
                if imported_layer not in allowed:
                    violations.append(
                        f"{py_file}: {file_layer} imports from {imported_layer} ({import_path})"
                    )

    # Check facade (hybrid.py)
    file_layer = get_layer_for_path(str(hybrid_py))
    if file_layer:
        for import_path in extract_imports(hybrid_py):
            imported_layer = get_imported_layer(import_path)
            if imported_layer and imported_layer != file_layer:
                allowed = ALLOWED_IMPORTS.get(file_layer, [])
                if imported_layer not in allowed:
                    violations.append(
                        f"{hybrid_py}: {file_layer} imports from {imported_layer} ({import_path})"
                    )

    assert not violations, "Layer violations found:\n" + "\n".join(violations)


@pytest.mark.unit
def test_models_have_no_internal_dependencies():
    """Verify models layer only imports stdlib/typing."""
    models_dir = Path("src/connectors/hybrid_backend/models")
    violations = []

    for py_file in models_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        for import_path in extract_imports(py_file):
            # Allow TYPE_CHECKING imports from core domain/interfaces
            if (
                import_path.startswith("src.")
                and "core.interfaces" not in import_path
                and "core.domain" not in import_path
            ):
                violations.append(f"{py_file}: models imports {import_path}")

    assert not violations, "Model layer violations:\n" + "\n".join(violations)
