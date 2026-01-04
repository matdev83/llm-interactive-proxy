import os
import sys

# Add src to python path
sys.path.append(os.getcwd())

from src.connectors.hybrid_backend.services.model_spec_parser import ModelSpecParser
from src.core.domain.model_utils import parse_model_with_params

try:
    result = parse_model_with_params("openai:gpt-4")
    print(f"parse_model_with_params returned type: {type(result)}")
    print(f"parse_model_with_params returned: {result}")

    # Try unpacking
    try:
        a, b, c = result
        print(f"Unpacked: {a}, {b}, {c}")
        print(f"Type of a: {type(a)}")
    except Exception as e:
        print(f"Unpacking failed: {e}")

    parser = ModelSpecParser()
    spec = parser.parse("hybrid:[openai:gpt-4,anthropic:claude-3]")
    print("Parsed spec successfully")

except Exception as e:
    print(f"Caught exception: {e}")
    import traceback

    traceback.print_exc()
