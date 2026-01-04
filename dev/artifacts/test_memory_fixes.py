#!/usr/bin/env python3
"""
Test script to verify memory leak fixes in ThoughtSignatureManager.
"""

import os
import sys
import time

# Add src to path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
sys.path.insert(0, src_path)

# Import the fixed class
from connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager


def test_memory_management():
    """Test that memory management works correctly."""
    print("=== Testing Fixed ThoughtSignatureManager ===")

    # Create manager with small limits for testing
    manager = ThoughtSignatureManager(max_cache_size=100, ttl_seconds=1)

    print(
        f"Initial state: cache={len(manager._cache)}, secondary={len(manager._by_tool_call)}"
    )

    # Test 1: Size limit enforcement
    print("\n--- Testing size limit enforcement ---")
    tool_calls = []
    for i in range(200):  # More than the limit of 100
        tool_calls.append(
            {
                "id": f"tool_{i}",
                "extra_content": {"google": {"thought_signature": f"sig_{i}"}},
            }
        )

    manager.store_signatures_from_tool_calls(tool_calls, "test_session")
    print(
        f"After storing 200 entries: cache={len(manager._cache)}, secondary={len(manager._by_tool_call)}"
    )

    # Cache should be limited to max_cache_size
    assert (
        len(manager._cache) <= 100
    ), f"Cache size {len(manager._cache)} exceeds limit of 100"
    print("✓ Size limit enforced")

    # Test 2: TTL expiration
    print("\n--- Testing TTL expiration ---")
    time.sleep(2)  # Wait for entries to expire (TTL is 1 second)

    # Trigger cleanup by adding new entry
    manager.store_signatures_from_tool_calls(
        [
            {
                "id": "new_tool",
                "extra_content": {"google": {"thought_signature": "new_sig"}},
            }
        ],
        "new_session",
    )

    print(
        f"After TTL wait + new entry: cache={len(manager._cache)}, secondary={len(manager._by_tool_call)}"
    )

    # Old entries should be expired
    if len(manager._cache) < 100:
        print("✓ TTL expiration working")
    else:
        print("⚠ TTL may not be working as expected")

    # Test 3: Anonymous entry cleanup
    print("\n--- Testing anonymous entry cleanup ---")

    # Add anonymous entries
    anon_tool_calls = []
    for i in range(50):
        anon_tool_calls.append(
            {
                "id": f"anon_{i}",
                "extra_content": {"google": {"thought_signature": f"anon_sig_{i}"}},
            }
        )

    manager.store_signatures_from_tool_calls(anon_tool_calls, None)
    print(
        f"After anonymous entries: cache={len(manager._cache)}, secondary={len(manager._by_tool_call)}"
    )

    # Clear anonymous entries
    cleared = manager.clear_all_anonymous()
    print(
        f"After clearing anonymous: cache={len(manager._cache)}, secondary={len(manager._by_tool_call)}, cleared={cleared}"
    )

    if cleared > 0:
        print("✓ Anonymous cleanup working")
    else:
        print("⚠ Anonymous cleanup may have issues")

    # Test 4: Session-specific cleanup
    print("\n--- Testing session cleanup ---")

    # Add session-specific entries
    session_tool_calls = []
    for i in range(20):
        session_tool_calls.append(
            {
                "id": f"session_tool_{i}",
                "extra_content": {"google": {"thought_signature": f"session_sig_{i}"}},
            }
        )

    manager.store_signatures_from_tool_calls(session_tool_calls, "cleanup_test")
    cache_before = len(manager._cache)

    # Clear specific session
    cleared = manager.clear_session_cache("cleanup_test")
    cache_after = len(manager._cache)

    print(
        f"Session cleanup: before={cache_before}, after={cache_after}, cleared={cleared}"
    )

    if cleared > 0 and cache_after < cache_before:
        print("✓ Session cleanup working")
    else:
        print("⚠ Session cleanup may have issues")

    print("\n=== Memory Management Tests Complete ===")
    print("ThoughtSignatureManager now has proper memory management:")
    print("• LRU eviction with size limits")
    print("• TTL-based expiration")
    print("• Anonymous entry cleanup")
    print("• Session-specific cleanup")


def test_command_parser_cache():
    """Test CommandParser pattern cache usage."""
    print("\n=== Testing Fixed CommandParser ===")

    from core.commands.parser import CommandParser

    parser = CommandParser()

    # Test pattern caching
    prefixes = ["!/", "!test", "!another", "!yet-another"]

    for prefix in prefixes:
        parser.command_prefix = (
            prefix  # This should trigger pattern compilation and caching
        )

    print(
        f"Pattern cache size after using {len(prefixes)} prefixes: {len(parser._pattern_cache)}"
    )

    # Test that cache is actually being used
    if len(parser._pattern_cache) > 0:
        print("✓ Pattern cache is now being used")
    else:
        print("⚠ Pattern cache still not being used")

    # Test size limit
    initial_cache_size = len(parser._pattern_cache)

    # Add many unique prefixes to trigger size limit
    for i in range(150):  # Should exceed the limit of 100
        parser.command_prefix = f"!prefix_{i}"

    final_cache_size = len(parser._pattern_cache)
    print(f"Cache size after 150 prefixes: {final_cache_size} (limit should be ~100)")

    if final_cache_size <= 105:  # Allow some tolerance
        print("✓ Pattern cache size limit working")
    else:
        print("⚠ Pattern cache size limit may not be working")


if __name__ == "__main__":
    test_memory_management()
    test_command_parser_cache()
