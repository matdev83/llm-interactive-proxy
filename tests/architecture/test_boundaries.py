import ast
import os

import pytest

REQUIRED_CLEAN_DIRECTORIES = [
    "src/core/services/backend_completion_flow",
]

FORBIDDEN_IMPORTS = [
    "fastapi",
    "starlette",
]


def get_python_files(directory):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                yield os.path.join(root, file)


def check_imports(file_path):
    with open(file_path, encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=file_path)
        except SyntaxError:
            pytest.fail(f"SyntaxError in {file_path}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in FORBIDDEN_IMPORTS:
                    if alias.name == forbidden or alias.name.startswith(
                        forbidden + "."
                    ):
                        return f"Line {node.lineno}: import {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            for forbidden in FORBIDDEN_IMPORTS:
                if node.module == forbidden or node.module.startswith(forbidden + "."):
                    return f"Line {node.lineno}: from {node.module} import ..."
    return None


@pytest.mark.parametrize("directory", REQUIRED_CLEAN_DIRECTORIES)
def test_no_transport_imports_in_orchestration(directory):
    """
    Ensure that backend orchestration modules do not import transport-layer libraries
    like FastAPI or Starlette.
    """
    if not os.path.exists(directory):
        pytest.fail(f"Directory {directory} does not exist")

    violations = []
    for file_path in get_python_files(directory):
        violation = check_imports(file_path)
        if violation:
            violations.append(f"{file_path}: {violation}")

    if violations:
        pytest.fail(
            "Transport layer leak detected! The following files import fastapi or starlette:\n"
            + "\n".join(violations)
        )
