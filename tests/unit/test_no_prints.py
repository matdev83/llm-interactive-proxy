import ast
import pathlib

ALLOWED_FILES = {
    pathlib.Path("src/main.py"),
}


def test_no_print_statements():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    for path in repo_root.rglob("*.py"):
        if (
            "tests" in path.parts
            or ".venv" in path.parts
            or "site-packages" in path.parts
            or ".git" in path.parts
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
        except (SyntaxError, ValueError) as e:
            # Log a warning or just skip if the file is not valid Python
            print(
                f"Skipping {path} due to parsing error: {e}"
            )  # Using print here for debugging the test itself
            continue
