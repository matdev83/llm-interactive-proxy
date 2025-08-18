#!/usr/bin/env python3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

backends = ["openrouter", "gemini", "openai", "zai", "anthropic"]
pattern = re.compile(r"(?P<var>\w+)\.app\.state\.(?P<attr>" + "|".join([b.replace('-', '_') for b in backends]) + r")_backend")

modified = 0
for fp in TESTS.rglob('*.py'):
    text = fp.read_text(encoding='utf-8')
    if 'app.state.' not in text:
        continue
    new_text = text
    def repl(m):
        var = m.group('var')
        attr = m.group('attr')
        backend_name = attr.replace('_','-')
        return f'get_backend_instance({var}.app, "{backend_name}")'

    new_text, count = pattern.subn(repl, text)
    if count:
        if 'from tests.conftest import get_backend_instance' not in new_text:
            # insert after initial imports
            lines = new_text.splitlines()
            insert_at = 0
            for i, l in enumerate(lines[:60]):
                if l.strip().startswith('import') or l.strip().startswith('from'):
                    insert_at = i + 1
            lines.insert(insert_at, 'from tests.conftest import get_backend_instance')
            new_text = '\n'.join(lines)
        fp.write_text(new_text, encoding='utf-8')
        print(f'Patched {fp} ({count} replacements)')
        modified += 1

print(f'Done. Modified {modified} files.')


