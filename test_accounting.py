#!/usr/bin/env python3
"""
Test script to check if llm-accounting library is working
"""

import os
import sys

def test_accounting_import():
    """Test if we can import and use the llm-accounting library"""
    print("Testing llm-accounting library...")
    
    try:
        from llm_accounting import LLMAccounting
        print("✅ LLMAccounting import successful")
        
        # Try to create an instance
        accounting = LLMAccounting()
        print("✅ LLMAccounting instance created")
        
        # Test basic functionality
        accounting.track_usage(
            model="test-model",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            cost=0.01,
            execution_time=1.0,
            caller_name="test"
        )
        print("✅ track_usage() works")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Error using LLMAccounting: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_our_accounting_utils():
    """Test our accounting utils"""
    print("\nTesting our llm_accounting_utils...")
    
    try:
        from src.llm_accounting_utils import get_llm_accounting, get_system_username
        print("✅ Import successful")
        
        # Test system username
        username = get_system_username()
        print(f"✅ System username: {username}")
        
        # Test getting accounting instance
        accounting = get_llm_accounting()
        print("✅ Got accounting instance")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_tiktoken():
    """Test tiktoken library"""
    print("\nTesting tiktoken library...")
    
    try:
        import tiktoken
        print("✅ tiktoken import successful")
        
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = encoding.encode("Hello world")
        print(f"✅ Encoded 'Hello world' to {len(tokens)} tokens")
        
        return True
        
    except Exception as e:
        print(f"❌ tiktoken error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = True
    success &= test_accounting_import()
    success &= test_our_accounting_utils()
    success &= test_tiktoken()
    
    if success:
        print("\n✅ All tests passed!")
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1) 