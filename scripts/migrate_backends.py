#!/usr/bin/env python3
"""Migrate test files from legacy app.state.<backend>_backend to DI helper get_backend_instance.

This script scans the tests/ directory for occurrences of patterns like
"<client_var>.app.state.<backend_attr>_backend" and replaces them with
"get_backend_instance(<client_var>.app, \"<backend_name>\")" where
<backend_name> is derived from <backend_attr> by replacing underscores with hyphens.

It also ensures that `from tests.conftest import get_backend_instance` is
imported at the top of the file if not already present.

Run from the repository root: python scripts/migrate_backends.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

pattern = re.compile(r"\b(?P<var>\w+)\.app\.state\.(?P<attr>[a-zA-Z0-9_]+)_backend\b")

files = list(TESTS.rglob("*.py"))
modified = 0
for fp in files:
    text = fp.read_text(encoding="utf-8")
    if "app.state." not in text:
        continue

    new_text = text
    replacements = []

    def repl(m: re.Match) -> str:
        var = m.group('var')
        attr = m.group('attr')
        backend_name = attr.replace('_', '-')
        replacements.append((m.group(0), f'get_backend_instance({var}.app, "{backend_name}")'))
        return f'get_backend_instance({var}.app, "{backend_name}")'

    new_text = pattern.sub(repl, text)

    if new_text != text:
        # ensure import exists
        import_line = 'from tests.conftest import get_backend_instance'
        if import_line not in new_text:
            # insert after imports block - naive: put at top after first 5 lines
            lines = new_text.splitlines()
            insert_at = 0
            for i, l in enumerate(lines[:50]):
                if l.strip().startswith('import') or l.strip().startswith('from'):
                    insert_at = i + 1
            lines.insert(insert_at, import_line)
            new_text = "\n".join(lines)

        fp.write_text(new_text, encoding="utf-8")
        modified += 1
        print(f"Modified {fp} -> {len(replacements)} replacements")

print(f"Done. Modified {modified} files.")


