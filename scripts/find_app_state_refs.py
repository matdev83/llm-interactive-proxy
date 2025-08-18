#!/usr/bin/env python3
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'tests'
pat = re.compile(r"(?P<line>.*app\.state\.[A-Za-z0-9_]+_backend.*)")
count=0
for fp in TESTS.rglob('*.py'):
    s = fp.read_text(encoding='utf-8')
    for i, line in enumerate(s.splitlines(), start=1):
        if 'app.state.' in line and '_backend' in line:
            print(f"{fp}:{i}: {line.strip()}")
            count+=1
print(f"Found {count} occurrences")



