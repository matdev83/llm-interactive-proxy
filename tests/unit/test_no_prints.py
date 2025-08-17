import ast
import pathlib

repo_root = pathlib.Path(__file__).resolve().parents[2]
ALLOWED_FILES = {
    repo_root / "src" / "main.py",
    repo_root / "dev" / "_client_call.py",
    repo_root / "tools" / "analyze_module_dependencies.py",
    repo_root / "tools" / "deprecate_legacy_endpoints.py",
}


def test_no_print_statements() -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    for path in repo_root.rglob("*.py"):
        if (
            "tests" in path.parts
            or ".venv" in path.parts
            or "site-packages" in path.parts
            or ".git" in path.parts
            or "dev" in path.parts
            or "examples" in path.parts
            or "tools" in path.parts
        ):
            continue
        if path in ALLOWED_FILES:
            continue
        if not path.is_file():  # Ensure it's a file, not a directory or symlink
            continue
        try:
            source = path.read_text()
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"
                ):
                    raise AssertionError(
                        f"print() found in {path} at line {node.lineno}"
                    )
        except (SyntaxError, ValueError):
            # Log a warning or just skip if the file is not valid Python
            # Using print here would violate our own rule, so we'll just continue
            continue
