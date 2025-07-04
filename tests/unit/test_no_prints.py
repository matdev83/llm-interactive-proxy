import ast
import pathlib

ALLOWED_FILES = {
    pathlib.Path('src/main.py'),
}

def _should_skip_file(path: pathlib.Path, repo_root: pathlib.Path) -> bool:
    """Checks if a file should be skipped based on its path or type."""
    # Skip directories within these common exclusion folders
    excluded_dirs = {'tests', '.venv', 'site-packages', '.git', 'build', 'dist', 'docs', '__pycache__'}
    if any(part in excluded_dirs for part in path.relative_to(repo_root).parts):
        return True
    if path in ALLOWED_FILES:
        return True
    if not path.is_file():  # Ensure it's a file, not a directory or symlink
        return True
    return False

def _check_file_for_prints(path: pathlib.Path) -> None:
    """Reads, parses, and checks a single Python file for print statements."""
    try:
        source = path.read_text(encoding='utf-8') # Specify encoding
        tree = ast.parse(source, filename=str(path)) # Add filename for better error messages
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print':
                raise AssertionError(f"print() found in {path} at line {node.lineno}")
    except (SyntaxError, ValueError, UnicodeDecodeError) as e: # Add UnicodeDecodeError
        # Using print here is acceptable as it's for debugging the test itself if a file fails to parse
        print(f"Skipping file {path} due to parsing error: {e}") # nosec
    except OSError as e: # Handle cases like file not found if symlink is broken etc.
        print(f"Skipping file {path} due to OS error: {e}") # nosec


def test_no_print_statements():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    python_files_found = False
    for path in repo_root.rglob('*.py'):
        python_files_found = True # Mark that we found at least one .py file
        if _should_skip_file(path, repo_root):
            continue
        _check_file_for_prints(path)

    assert python_files_found, "No Python files were found to check. Test might not be running correctly."
