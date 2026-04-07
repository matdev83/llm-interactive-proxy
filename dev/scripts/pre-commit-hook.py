#!/usr/bin/env python3
# ruff: noqa: N999
"""
Mandatory pre-commit hook for staged changes.

This hook enforces:
  - Secret scanning for staged files (API key leak prevention)
  - Disallowed file extension checks on staged files
  - Architectural linter on staged Python files (src/tests only)
  - Mypy type checking on staged Python files within src/
  - Pyright type checking on staged Python files (errors only; warnings ignored)
"""

import subprocess
import sys
from pathlib import Path
from shutil import which

_DISALLOWED_EXTENSIONS = {"db", "log", "cbor", "pyc", "tmp"}


def _repo_root() -> Path:
    """Resolve the repository root directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError("Unable to determine repository root") from e

    root = result.stdout.strip()
    if not root:
        raise RuntimeError("Unable to determine repository root")
    return Path(root)


def _python_executable(repo_root: Path) -> Path:
    """Return the preferred Python interpreter for repo tooling."""
    windows_venv = repo_root / ".venv" / "Scripts" / "python.exe"
    if windows_venv.exists():
        return windows_venv

    posix_venv = repo_root / ".venv" / "bin" / "python"
    if posix_venv.exists():
        return posix_venv

    return Path(sys.executable)


def _get_staged_files(repo_root: Path) -> list[str]:
    """Get a list of staged files (relative paths)."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    candidates = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [p for p in candidates if (repo_root / p).exists()]


def _is_generated_or_migration(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/")
    return "/migrations/" in normalized or "/generated/" in normalized


def _staged_python_files(repo_root: Path) -> list[str]:
    """Get a list of staged Python files (relative paths)."""
    staged_files = _get_staged_files(repo_root)
    return [p for p in staged_files if p.endswith(".py")]


def _staged_src_python_files(repo_root: Path) -> list[str]:
    """Get staged Python files under src/ (relative paths)."""
    files = _staged_python_files(repo_root)
    out: list[str] = []
    for p in files:
        normalized = p.replace("\\", "/")
        if normalized.startswith("src/") and not _is_generated_or_migration(p):
            out.append(p)
    return out


def _staged_pyright_files(repo_root: Path) -> tuple[list[str], list[str]]:
    """Split staged Python files into src files and non-src files (tests, etc.)."""
    files = _staged_python_files(repo_root)
    src_files: list[str] = []
    other_files: list[str] = []
    for p in files:
        normalized = p.replace("\\", "/")
        if _is_generated_or_migration(p):
            continue
        if normalized.startswith("src/"):
            src_files.append(p)
        else:
            other_files.append(p)
    return src_files, other_files


def _chunked(items: list[str], chunk_size: int) -> list[list[str]]:
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def check_disallowed_file_extensions() -> bool:
    """Fail the commit if disallowed file extensions are staged."""
    repo_root = _repo_root()
    staged_files = _get_staged_files(repo_root)

    violations: list[str] = []
    for file_path in staged_files:
        ext = Path(file_path).suffix.lower().lstrip(".")
        if ext in _DISALLOWED_EXTENSIONS:
            violations.append(file_path)

    if not violations:
        return True

    print("ERROR: Disallowed file extensions detected in staged files:")
    for file_path in sorted(violations):
        print(f"  - {file_path}")
    print(
        "\nThese extensions are blocked to prevent committing binary/log/temp artifacts:"
    )
    print(f"  {', '.join(sorted(_DISALLOWED_EXTENSIONS))}")
    return False


def get_changed_python_files() -> list[str]:
    """
    Get a list of changed Python files that are staged for commit.

    Returns:
        List of changed Python files
    """
    repo_root = _repo_root()
    return _staged_python_files(repo_root)


def check_architectural_patterns(files: list[str]) -> bool:
    """
    Check architectural patterns in the given files.

    Args:
        files: List of files to check

    Returns:
        True if all checks pass, False otherwise
    """
    repo_root = _repo_root()
    linter_path = repo_root / "dev" / "scripts" / "architectural_linter.py"

    # Verify the linter exists
    if not linter_path.exists():
        print(
            f"FATAL: Architectural linter not found at {linter_path}. "
            "This indicates a broken hook configuration.",
            file=sys.stderr,
        )
        return False

    # Find the Python interpreter to use
    python_path = _python_executable(repo_root)

    # Check each file
    any_errors = False

    for file_path in files:
        normalized_path = file_path.replace("\\", "/")
        if not normalized_path.startswith(("src/", "tests/")):
            continue
        if _is_generated_or_migration(file_path):
            continue

        print(f"Checking architectural patterns in: {file_path}")
        result = subprocess.run(
            [str(python_path), str(linter_path), file_path],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )

        # Check for errors
        if result.returncode != 0:
            print(f"Architectural violations found in {file_path}:")
            print(result.stdout)
            any_errors = True

    return not any_errors


def run_secret_scan() -> bool:
    """Run pre-commit API key check to prevent secret leaks.

    Returns True if no secrets are detected; False otherwise.
    """
    repo_root = _repo_root()
    checker_path = repo_root / "dev" / "scripts" / "pre_commit_api_key_check.py"

    if not checker_path.exists():
        print(
            f"FATAL: Secret checker not found at {checker_path}. "
            "This indicates a broken hook configuration. "
            "The pre-commit hook references a script that does not exist.",
            file=sys.stderr,
        )
        return False

    # Prefer project venv interpreter
    python_path = _python_executable(repo_root)

    print("Running secret scan on staged files...")
    result = subprocess.run(
        [str(python_path), str(checker_path)],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        # Surface the tool's output for the user
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return False

    # Optional verbosity
    if result.stdout.strip():
        print(result.stdout.strip())
    return True


def run_mypy_on_staged_src_files() -> bool:
    """Run mypy on staged Python files within src/ (errors fail the commit)."""
    repo_root = _repo_root()
    src_files = _staged_src_python_files(repo_root)
    if not src_files:
        return True

    python_path = _python_executable(repo_root)
    print(f"Running mypy on {len(src_files)} staged src/ files...")

    for chunk in _chunked(src_files, chunk_size=50):
        result = subprocess.run(
            [str(python_path), "-m", "mypy", *chunk],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        if result.returncode != 0:
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            return False

    return True


def _find_pyright_command(repo_root: Path) -> str | None:
    """Find a usable pyright command."""
    pyright = which("pyright") or which("pyright.cmd") or which("pyright.exe")
    if pyright:
        return pyright

    local_pyright = repo_root / "node_modules" / ".bin" / "pyright"
    if local_pyright.exists():
        return str(local_pyright)

    return None


def run_pyright_on_staged_files() -> bool:
    """Run pyright on staged Python files (errors only; warnings ignored)."""
    repo_root = _repo_root()
    src_files, other_files = _staged_pyright_files(repo_root)
    if not src_files and not other_files:
        return True

    pyright_cmd = _find_pyright_command(repo_root)
    if not pyright_cmd:
        print("Warning: pyright was not found; skipping pyright check.")
        print("To enable: npm install -g pyright")
        return True

    python_path = _python_executable(repo_root)

    def _run(project_file: str, files: list[str]) -> bool:
        if not files:
            return True
        for chunk in _chunked(files, chunk_size=50):
            try:
                result = subprocess.run(
                    [
                        pyright_cmd,
                        "--level",
                        "error",
                        "--pythonpath",
                        str(python_path),
                        "--project",
                        project_file,
                        *chunk,
                    ],
                    capture_output=True,
                    text=True,
                    cwd=repo_root,
                )
            except (FileNotFoundError, OSError) as e:
                print(f"Warning: pyright could not be executed ({e}); skipping.")
                return True
            if result.returncode != 0:
                if result.stdout:
                    print(result.stdout)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                return False
        return True

    if src_files:
        print(f"Running pyright (src profile) on {len(src_files)} files...")
        if not _run("pyrightconfig.src.json", src_files):
            return False

    # if other_files:
    #     print(f"Running pyright (project profile) on {len(other_files)} files...")
    #     if not _run("pyrightconfig.json", other_files):
    #         return False

    return True


def run_stall_linter_on_staged_tests() -> bool:
    """Run the stall-linter only when staged changes include tests/."""
    repo_root = _repo_root()
    staged_files = _get_staged_files(repo_root)
    has_any_tests_change = any(
        p.replace("\\", "/").startswith("tests/") for p in staged_files
    )
    if not has_any_tests_change:
        return True

    target_test_files = [
        p
        for p in staged_files
        if p.endswith(".py") and p.replace("\\", "/").startswith("tests/")
    ]
    if not target_test_files:
        return True

    python_path = _python_executable(repo_root)
    pytest_args: list[str] = [
        str(python_path),
        "-m",
        "pytest",
        "-n",
        "0",
        "tests/unit/test_stall_linter.py",
    ]
    for file_path in target_test_files:
        pytest_args.extend(["--stall-lint-file", file_path])

    print(f"Running stall-linter on {len(target_test_files)} staged tests files...")
    result = subprocess.run(pytest_args, capture_output=True, text=True, cwd=repo_root)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return False

    return True


def main() -> int:
    """
    Main entry point for the pre-commit hook.

    Returns:
        0 if successful, non-zero otherwise
    """
    # 1) Run secret scanning first to prevent leaks regardless of file type
    if not run_secret_scan():
        print("\nERROR: Secret scan failed; potential API keys detected.")
        print("Please remove sensitive values from staged files before committing.")
        return 1

    changed_files = get_changed_python_files()

    # 1b) Block accidental commits of binary/log/temp artifacts
    if not check_disallowed_file_extensions():
        print("\nERROR: Disallowed file types detected.")
        print("Please unstage these files before committing.")
        return 1

    # 1c) Stall linter on staged tests changes
    if not run_stall_linter_on_staged_tests():
        print("\nERROR: Stall-linter detected risky test patterns.")
        print("Fix the reported findings before committing.")
        return 1

    if not changed_files:
        print("No Python files changed, skipping architectural and type checks.")
        return 0

    # 2) Architectural checks
    print(f"Checking architectural patterns in {len(changed_files)} staged files...")
    if not check_architectural_patterns(changed_files):
        print("\nERROR: Architectural violations found!")
        print("Please fix these issues before committing.")
        print("Run dev/scripts/architectural_linter.py on your files for more details.")
        return 1

    # 3) Mypy on staged src/ python files only
    if not run_mypy_on_staged_src_files():
        print("\nERROR: mypy found type checking errors in staged src/ files.")
        print("Fix the errors or adjust types before committing.")
        return 1

    # 4) Pyright on staged python files (errors only)
    if not run_pyright_on_staged_files():
        print("\nERROR: pyright found errors in staged Python files.")
        print("Fix the errors or adjust types before committing.")
        return 1

    print("All pre-commit checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
