"""Verify the fix for whitespace chunk dropping."""

import sys

sys.path.insert(0, ".")

# Force reimport
import importlib

import src.core.ports.streaming_contracts

importlib.reload(src.core.ports.streaming_contracts)

from src.core.ports.streaming_contracts import StreamingContent

# Test whitespace content
print("Testing StreamingContent.is_empty for various content types:")
print("=" * 60)

test_cases = [
    ("Empty string", ""),
    ("Newline only", "\n"),
    ("Space only", " "),
    ("Tab only", "\t"),
    ("Multiple whitespace", "   "),
    ("Newline + space", "\n "),
    ("Non-whitespace", "text"),
    ("Text with whitespace", "hello world"),
    ("Dash", "-"),
]

for label, content in test_cases:
    sc = StreamingContent(content=content, metadata={})
    print(f"  {label!r:30} -> is_empty={sc.is_empty}")

# Expected results:
# - Empty string should be is_empty=True
# - Everything else (including whitespace) should be is_empty=False
