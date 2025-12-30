"""Remove outer try/except from _register_mock_backend_service function."""

# Read the file
with open("src/core/app/stages/test_stages.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Find the function boundaries
func_start = None
func_end = None
try_start = None
try_end = None

for i, line in enumerate(lines):
    if "def _register_mock_backend_service(" in line and "-> None:" in line:
        func_start = i
    if func_start is not None and line.strip() and not line.startswith(' ') and not line.startswith('\t') and i > func_start:
        func_end = i
        break

if func_start is None:
    print("Function not found!")
    exit(1)

# Find the outer try and except
for i in range(func_start, func_end):
    if '        try:' in lines[i] and 'try:' == lines[i].strip():
        # Check if this is at the right indent level for function body
        try_start = i
        break

if try_start is None:
    print("Outer try not found!")
    exit(1)

# Find the except clause that matches the outer try
for i in range(try_start + 1, func_end):
    if '        except ImportError as e:' in lines[i]:
        try_end = i + 3  # Skip except and the two logging lines
        break

if try_end is None:
    print("Outer except not found!")
    exit(1)

print(f"Function: lines {func_start+1} to {func_end}")
print(f"Outer try: line {try_start+1}")
print(f"Outer except: lines {try_end-2} to {try_end}")

# Remove the try line and except clause, unindent the body
# This is complex, so let's create new content
new_lines = []

# Add function header up to the try
new_lines.extend(lines[func_start:try_start])

# Add the try body with unindentation
for i in range(try_start + 1, try_end - 2):
    line = lines[i]
    # Unindent by 4 spaces (one level)
    if line.startswith("            "):
        new_lines.append("        " + line[12:])
    elif line.startswith("        "):
        new_lines.append("    " + line[8:])
    elif line.startswith("    "):
        new_lines.append(line[4:])
    else:
        new_lines.append(line)

# Add the rest of the file
new_lines.extend(lines[try_end:])

# Write back
with open("src/core/app/stages/test_stages.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Successfully removed outer try/except from _register_mock_backend_service")
