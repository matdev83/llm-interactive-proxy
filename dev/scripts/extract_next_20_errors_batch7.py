import json
import sys
import io

# Handle Windows encoding issues
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with open('dev/pyright_output.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

errors = [e for e in data.get('generalDiagnostics', []) if e.get('severity') == 'error']
print(f'Total errors: {len(errors)}')
print('\nNext 20 errors:')
for i, e in enumerate(errors[:20], 1):
    file_path = e['file'].replace('c:\\\\Users\\\\Mateusz\\\\source\\\\repos\\\\llm-interactive-proxy\\\\', '')
    line = e['range']['start']['line'] + 1  # Convert to 1-based
    char = e['range']['start']['character']
    msg = e['message'].replace('\u252c', '-').replace('\u2502', '|').replace('\u2514', '-').replace('\u2500', '-')
    rule = e.get('rule', 'N/A')
    print(f"{i}. {file_path}:{line}:{char} [{rule}]")
    print(f"   {msg}")
    print()
