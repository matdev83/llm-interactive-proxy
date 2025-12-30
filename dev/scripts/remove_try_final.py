"""Remove outer try/except from all target functions in test_stages.py."""

# Target functions and their approximate patterns
target_functions = [
    "_register_mock_backend_service",
    "_register_mock_backend_factory",
    "_register_backend_service",
    "_register_mock_command_service",
    "_register_mock_request_processor",
]

# Read the file
with open("src/core/app/stages/test_stages.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Process line by line
output = []
i = 0
in_outer_try = False
outer_try_indent = ""
indent_to_remove = ""

while i < len(lines):
    line = lines[i]
    stripped = line.strip()

    # Check if we're entering a target function
    for func_name in target_functions:
        if f"def {func_name}(" in line and " -> None:" in line:
            # Entering a target function
            if i + 2 < len(lines) and lines[i+1].strip().startswith('"""'):
                # Skip docstring
                if i + 2 < len(lines) and lines[i+2].strip().endswith('"""'):
                    # Single line docstring
                    output.append(line)
                    output.append(lines[i+1])
                    output.append(lines[i+2])
                    i += 3
                    if i < len(lines) and stripped == "try:" and not line.lstrip().startswith("try"):
                        # Found outer try
                        outer_try_indent = len(line) - len(line.lstrip())
                        indent_to_remove = " " * 4
                        in_outer_try = True
                        i += 1  # Skip the try line
                    continue
                elif i + 3 < len(lines) and '"""' in lines[i+3]:
                    # Multi-line docstring
                    output.append(line)
                    output.append(lines[i+1])
                    output.append(lines[i+2])
                    output.append(lines[i+3])
                    i += 4
                    if i < len(lines) and lines[i].strip() == "try:" and len(lines[i]) - len(lines[i].lstrip()) == 8:
                        # Found outer try at 8-space indent
                        outer_try_indent = 8
                        indent_to_remove = " " * 4
                        in_outer_try = True
                        i += 1  # Skip the try line
                    continue

    # Check if we're in an outer try block
    if in_outer_try:
        # Check for the except clause at the same indent as the try
        if stripped.startswith("except ImportError as e:") and len(line) - len(stripped) == outer_try_indent:
            # Skip except and the next 2 lines
            in_outer_try = False
            i += 3
            continue

        # Unindent the line
        if line.startswith(" " * (outer_try_indent + 4)):
            output.append(" " * outer_try_indent + line[outer_try_indent + 4:])
        elif line.startswith(" " * (outer_try_indent + 8)):
            output.append(" " * (outer_try_indent + 4) + line[outer_try_indent + 8:])
        else:
            output.append(line)
    else:
        output.append(line)

    i += 1

# Write back
with open("src/core/app/stages/test_stages.py", "w", encoding="utf-8") as f:
    f.writelines(output)

print("Successfully processed test_stages.py")
