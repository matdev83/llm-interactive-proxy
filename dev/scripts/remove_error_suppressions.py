"""Script to remove error suppressions from test_stages.py"""

import re

# Read the file
with open("src/core/app/stages/test_stages.py", encoding="utf-8") as f:
    content = f.read()

# Define patterns to remove
patterns_to_remove = [
    # Pattern 1: _override_session_service_for_test_compatibility
    (
        r'(\n        def _override_session_service_for_test_compatibility\(.*?\) -> None:\n        """.*?"""\n)        try:',
        r"\1        ",
    ),
    (
        r'(\n                logger\.debug\("Overrode session service to ensure real Session objects"\)\n)(        except ImportError as e:\n            if logger\.isEnabledFor\(logging\.WARNING\):\n                logger\.warning\("Could not override session service: %s", e\))',
        r"\1",
    ),
    # Pattern 2: _register_backend_config_provider
    (
        r'(\n    def _register_backend_config_provider\(self, services: ServiceCollection\) -> None:\n        """.*?"""\n)        try:',
        r"\1        ",
    ),
    (
        r'(\n                logger\.debug\("Registered mock backend config provider"\)\n)(        except ImportError as e:\n            if logger\.isEnabledFor\(logging\.WARNING\):\n                logger\.warning\("Could not register mock backend config provider: %s", e\))',
        r"\1",
    ),
    # Pattern 3: _register_mock_backend_factory
    (
        r'(\n    def _register_mock_backend_factory\(.*?\) -> None:\n        """.*?"""\n)        try:',
        r"\1        ",
    ),
    (
        r'(\n                logger\.debug\("Registered mock backend factory"\)\n)(        except ImportError as e:\n            if logger\.isEnabledFor\(logging\.WARNING\):\n                logger\.warning\("Could not register mock backend factory: %s", e\))',
        r"\1",
    ),
    # Pattern 4: _register_backend_service
    (
        r'(\n    def _register_backend_service\(.*?\) -> None:\n        """.*?"""\n)        try:',
        r"\1        ",
    ),
    (
        r'(\n                logger\.debug\("Registered BackendService with all dependencies"\)\n)(        except ImportError as e:\n            if logger\.isEnabledFor\(logging\.WARNING\):\n                logger\.warning\("Could not register mock backend factory: %s", e\))',
        r"\1",
    ),
    # Pattern 5: _register_mock_command_service
    (
        r'(\n    def _register_mock_command_service\(self, services: ServiceCollection\) -> None:\n        """.*?"""\n)        try:',
        r"\1        ",
    ),
    (
        r'(\n                logger\.debug\("Registered mock command service"\)\n)(        except ImportError as e:\n            if logger\.isEnabledFor\(logging\.WARNING\):\n                logger\.warning\("Could not register mock command service: %s", e\))',
        r"\1",
    ),
    # Pattern 6: _register_mock_request_processor
    (
        r'(\n    def _register_mock_request_processor\(self, services: ServiceCollection\) -> None:\n        """.*?"""\n)        try:',
        r"\1        ",
    ),
    (
        r'(\n                logger\.debug\("Registered mock request processor"\)\n)(        except ImportError as e:\n            if logger\.isEnabledFor\(logging\.WARNING\):\n                logger\.warning\("Could not register mock request processor: %s", e\))',
        r"\1",
    ),
]

# Apply patterns
modified_content = content
for pattern, replacement in patterns_to_remove:
    modified_content = re.sub(pattern, replacement, modified_content, flags=re.DOTALL)

# Special handling for _register_mock_backend_service which is larger
# This function has legitimate inner exception handlers, so we need to be careful
# We'll remove just the outer try/except wrapper

# Find and replace the outer try in _register_mock_backend_service
lines = modified_content.split("\n")
output_lines = []
in_function = False
skip_next = False
try_level = 0  # Track nested try blocks
brace_level = 0  # Track indentation level
target_function_start = None

i = 0
while i < len(lines):
    line = lines[i]

    # Check if we're entering _register_mock_backend_service
    if "def _register_mock_backend_service(" in line and "-> None:" in line:
        in_function = True
        target_function_start = i
        output_lines.append(line)
        i += 1
        continue

    if in_function:
        # Check for the outer 'try:' at the function level
        # We need to find the try that comes right after the docstring
        if i == target_function_start + 2 and line.strip() == "try:":
            # This is the outer try - skip it
            skip_next = True
            i += 1
            continue

        # Check for the except clause at the same level as the def
        if line.strip().startswith("except ImportError as e:"):
            # Skip this and the next 2 lines (the logging warning)
            skip_next = True
            i += 1
            continue
        elif (
            line.strip().startswith("if logger.isEnabledFor(logging.WARNING):")
            and "Could not register mock backend service" in lines[i + 1]
            if i + 1 < len(lines)
            else False
        ) or line.strip().startswith(
            'logger.warning("Could not register mock backend service:'
        ):
            skip_next = True
            i += 1
            continue

        # End of function detection
        if line.strip() and not line.startswith(" ") and not line.startswith("\t"):
            in_function = False
            target_function_start = None

    output_lines.append(line)
    i += 1

modified_content = "\n".join(output_lines)

# Write back
with open("src/core/app/stages/test_stages.py", "w", encoding="utf-8") as f:
    f.write(modified_content)

print("Successfully removed error suppressions from test_stages.py")
