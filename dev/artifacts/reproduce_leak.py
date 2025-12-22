
import sys
import uuid
from src.core.domain.translation_utils.tool_call_state import (
    cache_function_name,
    _codex_function_name_cache,
    reset_tool_call_state
)

def main():
    print("Starting leak reproduction...")
    initial_size = len(_codex_function_name_cache)
    print(f"Initial cache size: {initial_size}")

    iterations = 10000
    print(f"Adding {iterations} entries...")
    
    for _ in range(iterations):
        call_id = str(uuid.uuid4())
        name = "some_function_name"
        cache_function_name(call_id, name)
        # Even if we try to reset (though it doesn't cover this cache), it shouldn't help
        reset_tool_call_state("some_response_id")

    final_size = len(_codex_function_name_cache)
    print(f"Final cache size: {final_size}")

    if final_size >= initial_size + iterations:
        print("FAIL: Cache grew unboundedly!")
        sys.exit(1)
    else:
        print("SUCCESS: Cache size is contained.")
        sys.exit(0)

if __name__ == "__main__":
    main()
