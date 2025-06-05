import ast
import pathlib

ALLOWED_FILES = {
    pathlib.Path('src/main.py'),
}


def test_no_print_statements():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    for path in repo_root.rglob('*.py'):
        if 'tests' in path.parts:
            continue
        if path in ALLOWED_FILES:
            continue
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print':
                raise AssertionError(f"print() found in {path} at line {node.lineno}")
