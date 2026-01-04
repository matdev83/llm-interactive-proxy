"""Script to update test_model_utils_uri.py tests to use ParsedModelWithParams."""

import re

# Read the file
with open(r"tests\unit\core\domain\test_model_utils_uri.py", encoding="utf-8") as f:
    content = f.read()

# Replace all patterns like:
# backend, model, params = parse_model_with_params(...)
# assert backend == ...
# assert model == ...
# assert params == ...

# Pattern 1: Replace the function call
content = re.sub(
    r"(\s+)backend, model, params = parse_model_with_params\(([^)]+)\))",
    r"\1result = parse_model_with_params(\2)",
    content,
)

# Pattern 2: Replace assert backend
content = re.sub(
    r"assert backend == (.+)", r"assert result.backend_type == \1", content
)

# Pattern 3: Replace assert model
content = re.sub(r"assert model == (.+)", r"assert result.model_name == \1", content)

# Pattern 4: Replace assert params == (with dict)
content = re.sub(
    r"assert params == ({[^}]+})", r"assert result.uri_params == \1", content
)

# Write back
with open(
    r"tests\unit\core\domain\test_model_utils_uri.py", "w", encoding="utf-8"
) as f:
    f.write(content)

print("Updated test_model_utils_uri.py")
