#!/usr/bin/env python3
"""Surgically remove only try/except lines without changing indentation."""

# List of specific line numbers (1-indexed) from original file that need removal:
# Try lines: 47, 160, 197, 683, 729, 929, 946
# Except+logging blocks: 72-74, 185-187, 675-677, 723-725, 890-892, 940-942, 967-969

import subprocess

# Get original content to find exact line strings
result = subprocess.run(
    ["git", "show", "HEAD:src/core/app/stages/test_stages.py"],
    capture_output=True,
    text=True,
    check=True,
)
original_lines = result.stdout.split("\n")

# Lines to remove (0-indexed)
lines_to_remove = set()
lines_to_remove.update([46, 159, 196, 682, 728, 928, 945])  # Try lines
lines_to_remove.update(range(71, 74))  # 72-74 except+logging
lines_to_remove.update(range(184, 187))  # 185-187
lines_to_remove.update(range(674, 677))  # 675-677
lines_to_remove.update(range(722, 725))  # 723-725
lines_to_remove.update(range(889, 892))  # 890-892
lines_to_remove.update(range(939, 942))  # 940-942
lines_to_remove.update(range(966, 969))  # 967-969

# Read current file
with open("src/core/app/stages/test_stages.py", encoding="utf-8") as f:
    content = f.read()

# Split by newline but preserve structure
lines = content.split("\n")

# Filter out lines to remove
output = []
for i, line in enumerate(lines):
    if i not in lines_to_remove:
        output.append(line)

# Write back
with open(
    "src/core/app/stages/test_stages.py", "w", encoding="utf-8", newline="\n"
) as f:
    f.write("\n".join(output))

print("Surgically removed suppressions")
