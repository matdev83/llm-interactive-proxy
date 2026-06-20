import json
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.getcwd())

from src.core.domain.translation import Translation

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def demo_fix():
    print("=" * 80)
    print("DEMO: Gemini Schema Sanitization Fix")
    print("=" * 80)

    # The problematic TodoWrite schema that was causing 400 INVALID_ARGUMENT
    # It has:
    # 1. 'anyOf' at the top level of 'todos' property (Union[List[...], str])
    # 2. Tuple validation in 'items' (List[Schema1, Schema2]) inside the first option
    problematic_schema = {
        "type": "object",
        "properties": {
            "todos": {
                "anyOf": [
                    {
                        "type": "array",
                        "items": [
                            {
                                "type": "object",
                                "properties": {
                                    "content": {
                                        "type": "string",
                                        "description": "The content",
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": ["pending", "done"],
                                    },
                                },
                                "required": ["content", "status"],
                            },
                            {"type": "string"},
                        ],
                        "description": "List of todo items",
                    },
                    {
                        "type": "string",
                        "description": "Alternative string representation",
                    },
                ],
                "description": "The updated todo list",
            }
        },
        "required": ["todos"],
    }

    print("\n[1] Original Problematic Schema:")
    print(json.dumps(problematic_schema, indent=2))

    # Apply sanitization
    sanitized_schema = Translation._sanitize_gemini_parameters(problematic_schema)

    print("\n[2] Sanitized Schema (What is sent to Gemini):")
    print(json.dumps(sanitized_schema, indent=2))

    # Verification steps
    print("\n[3] Verification:")

    todos_prop = sanitized_schema["properties"]["todos"]

    # Check 1: Flattening of anyOf
    if "anyOf" not in todos_prop:
        print("[OK] PASS: 'anyOf' removed from 'todos' property.")
    else:
        print("[FAIL] FAIL: 'anyOf' still present in 'todos' property.")

    # Check 2: Selection of first option
    if todos_prop.get("type") == "array":
        print("[OK] PASS: First option (array) selected from Union.")
    else:
        print(f"[FAIL] FAIL: Expected type 'array', got '{todos_prop.get('type')}'.")

    # Check 3: Simplification of tuple items
    items = todos_prop.get("items")
    if items == {}:
        print("[OK] PASS: Tuple 'items' converted to empty schema {} (allow anything).")
    else:
        print(f"[FAIL] FAIL: 'items' is not empty schema. Got: {items}")

    # Check 4: No forbidden keywords
    forbidden = ["anyOf", "oneOf", "allOf"]
    found_forbidden = []

    def check_forbidden(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in forbidden:
                    found_forbidden.append(k)
                check_forbidden(v)
        elif isinstance(obj, list):
            for item in obj:
                check_forbidden(item)

    check_forbidden(sanitized_schema)

    if not found_forbidden:
        print(
            "[OK] PASS: No forbidden keywords (anyOf, oneOf, allOf) found in entire schema."
        )
    else:
        print(f"[FAIL] FAIL: Found forbidden keywords: {found_forbidden}")


if __name__ == "__main__":
    demo_fix()
