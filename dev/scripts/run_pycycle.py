#!/usr/bin/env python3
"""
Run pycycle using settings from ``[tool.pycycle]`` in the repository ``pyproject.toml``.

Upstream ``pycycle --source <path>`` is unusable with current Click (the option is typed as a
boolean), so this script invokes ``pycycle --here`` with the working directory set to
``resolve_dir`` (typically ``src`` for this layout).

Usage::

    ./.venv/Scripts/python.exe dev/scripts/run_pycycle.py
    ./.venv/Scripts/python.exe dev/scripts/run_pycycle.py --verbose
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import tomli


def _find_pyproject(start: Path) -> Path:
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    msg = "pyproject.toml not found (expected an ancestor of this script)."
    raise SystemExit(msg)


def _load_pycycle_config(pyproject_path: Path) -> dict[str, Any]:
    with pyproject_path.open("rb") as handle:
        data = tomli.load(handle)
    tool = data.get("tool") or {}
    if not isinstance(tool, Mapping):
        return {}
    pycycle = tool.get("pycycle") or {}
    if not isinstance(pycycle, Mapping):
        return {}
    return dict(pycycle)


def _pycycle_executable() -> str:
    scripts_dir = Path(sys.executable).resolve().parent
    for name in ("pycycle.exe", "pycycle"):
        candidate = scripts_dir / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("pycycle")
    if found:
        return found
    msg = (
        "pycycle executable not found. Install dev dependencies, for example: "
        "pip install -e .[dev]"
    )
    raise SystemExit(msg)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose pycycle output (overrides [tool.pycycle].verbose when set).",
    )
    args = parser.parse_args()

    script_path = Path(__file__).resolve()
    pyproject_path = _find_pyproject(script_path.parent)
    repo_root = pyproject_path.parent
    cfg = _load_pycycle_config(pyproject_path)

    resolve_dir = str(cfg.get("resolve_dir") or "src")
    encoding = cfg.get("encoding")
    ignore = str(cfg.get("ignore") or "")
    verbose = bool(cfg.get("verbose")) or args.verbose

    target = (repo_root / resolve_dir).resolve()
    try:
        target.relative_to(repo_root.resolve())
    except ValueError:
        msg = f"resolve_dir {resolve_dir!r} escapes repository root."
        raise SystemExit(msg)
    if not target.is_dir():
        msg = f"Analysis directory does not exist: {target}"
        raise SystemExit(msg)

    cmd: list[str] = [_pycycle_executable(), "--here"]
    if encoding:
        cmd.extend(["--encoding", str(encoding)])
    stripped_ignore = ignore.strip()
    if stripped_ignore:
        cmd.extend(["--ignore", stripped_ignore])
    if verbose:
        cmd.append("--verbose")

    completed = subprocess.run(cmd, cwd=target, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
