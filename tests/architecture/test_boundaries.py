import io
import os
import tokenize

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


def matches_forbidden_module(module_name):
    for forbidden in FORBIDDEN_IMPORTS:
        if module_name == forbidden or module_name.startswith(forbidden + "."):
            return True
    return False


def advance_to_statement_end(tokens, index):
    while index < len(tokens):
        token = tokens[index]
        if token.type == tokenize.NEWLINE or token.string == ";":
            return index + 1
        index += 1
    return index


def parse_from_module(tokens, index):
    parts = []
    while index < len(tokens):
        token = tokens[index]
        if token.type == tokenize.NL:
            index += 1
            continue
        if token.type == tokenize.NAME and token.string == "import":
            break
        if token.type == tokenize.NAME:
            parts.append(token.string)
        elif token.string == ".":
            parts.append(".")
        elif token.type == tokenize.NEWLINE or token.string == ";":
            break
        index += 1
    module_name = "".join(parts).lstrip(".")
    return module_name or None, index


def parse_import_modules(tokens, index):
    modules = []
    current = []
    while index < len(tokens):
        token = tokens[index]
        if token.type == tokenize.NL:
            index += 1
            continue
        if token.type == tokenize.NEWLINE or token.string == ";":
            break
        if token.type == tokenize.NAME:
            if token.string == "as":
                if current:
                    modules.append("".join(current))
                    current = []
                index += 1
                while index < len(tokens) and tokens[index].type == tokenize.NL:
                    index += 1
                if index < len(tokens) and tokens[index].type == tokenize.NAME:
                    index += 1
                continue
            current.append(token.string)
        elif token.string == ".":
            if current:
                current.append(".")
        elif token.string == ",":
            if current:
                modules.append("".join(current))
                current = []
        index += 1
    if current:
        modules.append("".join(current))
    return modules, index


def find_forbidden_import(tokens):
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == tokenize.NAME and token.string == "from":
            module_name, next_index = parse_from_module(tokens, index + 1)
            if module_name and matches_forbidden_module(module_name):
                return f"Line {token.start[0]}: from {module_name} import ..."
            index = advance_to_statement_end(tokens, next_index)
            continue
        if token.type == tokenize.NAME and token.string == "import":
            modules, next_index = parse_import_modules(tokens, index + 1)
            for module_name in modules:
                if matches_forbidden_module(module_name):
                    return f"Line {token.start[0]}: import {module_name}"
            index = advance_to_statement_end(tokens, next_index)
            continue
        index += 1
    return None


def check_imports(file_path):
    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        pytest.fail(f"Unable to read {file_path}: {exc}")

    if not any(forbidden in source for forbidden in FORBIDDEN_IMPORTS):
        return None

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError as exc:
        pytest.fail(f"TokenError in {file_path}: {exc}")

    return find_forbidden_import(tokens)


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
