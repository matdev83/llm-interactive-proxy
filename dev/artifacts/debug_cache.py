#!/usr/bin/env python3
"""
Debug test for cache property
"""

import sys
import os

# Add src to path
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, src_path)

from connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager

def test_cache_property():
    """Test cache property getter/setter"""
    print("=== Testing Cache Property ===")
    
    manager = ThoughtSignatureManager()
    
    # Test setting via property
    manager.cache["test_key"] = "test_value"
    print(f"After setting one entry: cache size = {len(manager._cache)}")
    print(f"Internal cache structure: {dict(manager._cache)}")
    
    # Test getting via property
    retrieved_cache = manager.cache
    print(f"Retrieved cache: {retrieved_cache}")
    
    # Set multiple entries
    manager.cache.update({
        "key1": "value1",
        "key2": "value2",
        "test_key": "updated_value"
    })
    print(f"After update: cache size = {len(manager._cache)}")
    print(f"Internal cache after update: {dict(manager._cache)}")
    
    # Test getter again
    final_cache = manager.cache
    print(f"Final cache: {final_cache}")
    
    # Verify injection works
    print("\n--- Testing Injection ---")
    from connectors.gemini_base.thought_signature_service import ThoughtSignatureService
    
    service = ThoughtSignatureService(use_global_cache=False)
    service._manager = manager  # Use our test manager directly
    
    # Set up cache as test expects
    cache_key = "test_session_abc:call_test123"
    service.cache[cache_key] = "cached_signature_xyz"
    
    print(f"Service cache after setting: {service.cache}")
    print(f"Manager cache after setting: {manager.cache}")
    
    # Mock a tool call and inject
    class MockToolCall:
        def __init__(self):
            self.id = "call_test123"
            self.extra_content = None
    
    class MockMessage:
        def __init__(self):
            self.tool_calls = [MockToolCall()]
    
    class MockRequest:
        def __init__(self):
            self.messages = [MockMessage()]
    
    req = MockRequest()
    service.inject_signatures(req, "test_session_abc")
    
    print(f"After injection: extra_content = {req.messages[0].tool_calls[0].extra_content}")
    
    if req.messages[0].tool_calls[0].extra_content:
        print("✓ Injection successful")
    else:
        print("✗ Injection failed")

if __name__ == "__main__":
    test_cache_property()