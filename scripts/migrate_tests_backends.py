#!/usr/bin/env python3
"""Migrate test files to DI-only backend access.

Replacements performed:
- Replace occurrences of `<var>.app.state.<backend>_backend` with
  `get_backend_instance(<var>.app, "<backend>")`.
- Replace simple assignments like
  `<var>.app.state.<backend>_backend = <expr>` with
  `svc = <var>.app.state.service_provider.get_required_service(IBackendService)\n`\
  `svc._backends["<backend>"] = <expr>`

The script adds necessary imports (`get_backend_instance`, `IBackendService`) if
they're not already present. It edits files in-place and creates a `.bak` backup
next to each changed file.

Run from project root: `python scripts/migrate_tests_backends.py`
"""
import re
from pathlib import Path
from shutil import copy2

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

access_pattern = re.compile(
    r"(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*app\s*\.\s*state\s*\.\s*(?P<attr>[A-Za-z0-9_]+)_backend\b"
)
assign_pattern = re.compile(
    r"(?P<prefix>\s*)(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*app\s*\.\s*state\s*\.\s*(?P<attr>[A-Za-z0-9_]+)_backend\s*=\s*(?P<expr>.+)"
)


def ensure_import(text: str, import_line: str) -> str:
    if import_line in text:
        return text
    # Try to insert after top import block
    lines = text.splitlines()
    insert_at = 0
    for i, l in enumerate(lines[:60]):
        if l.strip().startswith("import") or l.strip().startswith("from"):
            insert_at = i + 1
    lines.insert(insert_at, import_line)
    return "\n".join(lines)


modified_files = 0
for fp in TESTS.rglob("*.py"):
    text = fp.read_text(encoding="utf-8")
    orig = text
    if "app.state." not in text:
        continue

    # Handle simple assignment replacements first
    def assign_repl(m):
        prefix = m.group("prefix") or ""
        var = m.group("var")
        attr = m.group("attr")
        expr = m.group("expr").rstrip()
        backend_name = attr.replace("_", "-")
        svc_line = f"{prefix}svc = {var}.app.state.service_provider.get_required_service(IBackendService)"
        set_line = f'{prefix}svc._backends["{backend_name}"] = {expr}'
        return svc_line + "\n" + set_line

    text, count_assign = assign_pattern.subn(assign_repl, text)

    # Replace attribute accesses
    def access_repl(m):
        var = m.group("var")
        attr = m.group("attr")
        backend_name = attr.replace("_", "-")
        return f'get_backend_instance({var}.app, "{backend_name}")'

    text, count_access = access_pattern.subn(access_repl, text)

    if count_assign or count_access:
        # backup
        bak = fp.with_suffix(fp.suffix + ".bak")
        copy2(fp, bak)
        # ensure imports
        text = ensure_import(text, "from tests.conftest import get_backend_instance")
        text = ensure_import(
            text,
            "from src.core.interfaces.backend_service_interface import IBackendService",
        )
        fp.write_text(text, encoding="utf-8")
        modified_files += 1
        print(
            f"Patched {fp} (assigns={count_assign}, accesses={count_access}) -> backup {bak}"
        )

print(f"Done. Modified {modified_files} files.")
