"""Script to remove try/except blocks from test_stages.py using line-by-line processing."""

# Read the file
with open("src/core/app/stages/test_stages.py", encoding="utf-8") as f:
    lines = f.readlines()

# Process lines to remove try/except wrappers
output_lines = []
skip_indent_adjustment = False
current_indent_level = 0
in_target_function = False
target_function_depth = 0
try_start_line = -1
in_try_block = False

# Functions to process
target_functions = [
    "_override_session_service_for_test_compatibility",
    "_register_backend_config_provider",
    "_register_mock_backend_service",
    "_register_mock_backend_factory",
    "_register_backend_service",
    "_register_mock_command_service",
    "_register_mock_request_processor",
]

i = 0
while i < len(lines):
    line = lines[i]
    stripped = line.strip()

    # Check if we're entering a target function
    for func_name in target_functions:
        if f"def {func_name}(" in stripped and " -> None:" in line:
            in_target_function = True
            target_function_depth = 0
            output_lines.append(line)
            i += 1
            continue

    if in_target_function:
        # Check for outer try at function level (no leading content before def)
        if i > 0 and stripped == "try:" and not line.lstrip().startswith("try"):
            # This is an outer try block - skip it and flag to unindent following lines
            try_start_line = len(output_lines)  # Position after the def/docstring
            in_try_block = True
            skip_indent_adjustment = False
            i += 1
            continue

        # Check for except clause that matches the outer try
        if in_try_block and stripped.startswith("except ImportError as e:"):
            # Skip this except block
            # Check next line for logging
            if (
                i + 1 < len(lines)
                and "logger.isEnabledFor" in lines[i + 1]
                and "logger.warning" in lines[i + 2]
            ):
                i += 3  # Skip except and the two logging lines
            else:
                i += 1  # Just skip except
            in_try_block = False
            continue

        # Adjust indentation for lines inside a removed try block
        if in_try_block and line.strip():
            # Unindent by 4 spaces (one level)
            if line.startswith("            "):  # 12 spaces
                output_lines.append("        " + line[12:])  # 8 spaces
            elif line.startswith("        "):  # 8 spaces
                output_lines.append("    " + line[8:])  # 4 spaces
            elif line.startswith("    "):  # 4 spaces
                output_lines.append(line[4:])  # 0 spaces
            else:
                output_lines.append(line)
        else:
            output_lines.append(line)

        # Check if we've exited the function
        if (
            stripped
            and not line.startswith(" ")
            and not line.startswith("\t")
            and stripped not in target_functions
        ):
            # We've exited the function
            in_target_function = False
            in_try_block = False
    else:
        output_lines.append(line)

    i += 1

# Write the modified content back
with open("src/core/app/stages/test_stages.py", "w", encoding="utf-8") as f:
    f.writelines(output_lines)

print("Successfully removed try/except blocks from test_stages.py")
