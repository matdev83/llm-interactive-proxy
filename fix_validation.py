#!/usr/bin/env python3
"""Fix the gemini_oauth_antigravity.py file to disable model validation."""

import sys

# Read the file
with open("src/connectors/gemini_oauth_antigravity.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace the validation lines
old_text = """        # Validate the model is available on this backend
        self.validate_model(model_name)"""

new_text = """        # Skip model validation - Antigravity sandbox supports both Gemini and Claude models
        # NOTE: Claude models have limited tool calling support on this backend.
        # Gemini's functionCall format does not preserve tool call IDs, which are required
        # when Antigravity converts to Anthropic format for Claude. This may cause errors
        # in multi-turn conversations with tool use.
        # self.validate_model(model_name)"""

if old_text in content:
    content = content.replace(old_text, new_text)
    with open("src/connectors/gemini_oauth_antigravity.py", "w", encoding="utf-8", newline="\r\n") as f:
        f.write(content)
    print("✅ Successfully updated gemini_oauth_antigravity.py")
else:
    print("❌ Could not find the text to replace")
    sys.exit(1)
