#!/usr/bin/env python3
"""More robust migrator for app.state.<backend>_backend -> get_backend_instance(...)

This script finds occurrences of <var>.app.state.<attr>_backend and replaces
them with get_backend_instance(<var>.app, "<backend>"). It handles various
spacing and punctuation and adds the import if missing.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

pattern = re.compile(
    r"(?P<prefix>\b)(?P<var>\w+)\s*\.\s*app\s*\.\s*state\s*\.\s*(?P<attr>[a-zA-Z0-9_]+)_backend(?P<suffix>\b)"
)

files = list(TESTS.rglob("*.py"))
modified = 0
for fp in files:
    text = fp.read_text(encoding="utf-8")
    if "app.state" not in text:
        continue

    def repl(m):
        var = m.group("var")
        attr = m.group("attr")
        backend_name = attr.replace("_", "-")
        return f'get_backend_instance({var}.app, "{backend_name}")'

    new_text, count = pattern.subn(repl, text)
    if count > 0:
        # ensure import present
        import_line = "from tests.conftest import get_backend_instance"
        if import_line not in new_text:
            # try to place after other imports
            lines = new_text.splitlines()
            insert_at = 0
            for i, l in enumerate(lines[:60]):
                if l.strip().startswith("import") or l.strip().startswith("from"):
                    insert_at = i + 1
            lines.insert(insert_at, import_line)
            new_text = "\n".join(lines)
        fp.write_text(new_text, encoding="utf-8")
        modified += 1
        print(f"Patched {fp} ({count} replacements)")

print(f"Done. Modified {modified} files.")
