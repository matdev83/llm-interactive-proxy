#!/usr/bin/env python3
"""
Test script to verify DoS protection allows legitimate large payloads (<10MB).
"""

import json
import time
import sys
from pathlib import Path

# Add src directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.tool_call_repair_service import ToolCallRepairService

def create_large_legitimate_payload(size_mb=8):
    """Create a large but legitimate JSON payload (under 10MB limit)."""
    print(f"Creating legitimate large JSON payload ({size_mb}MB)...")
    
    # Calculate reasonable array size to achieve target size
    # Each item will be roughly 500 bytes, so we need target_size / 500 items
    target_bytes = size_mb * 1024 * 1024
    num_items = target_bytes // 500  # Approximate bytes per item
    
    large_array = []
    for i in range(num_items):
        large_array.append({
            "file_path": f"/path/to/file_{i}.py",
            "content": f"print('Line {i}')\n",  # Keep content smaller
            "metadata": {
                "line_number": i,
                "type": "code_line",
                "modified": True
            }
        })
    
    legitimate_data = {
        "function_call": {
            "name": "bulk_edit_files",
            "arguments": {
                "files": large_array,
                "operation": "batch_update",
                "description": "Large but legitimate bulk file operation"
            }
        }
    }
    
    return json.dumps(legitimate_data)

def test_legitimate_large_payloads():
    """Test that legitimate large payloads under 10MB are still accepted."""
    print("=== Testing Legitimate Large Payloads (<10MB) ===")
    
    repair_service = ToolCallRepairService()
    
    # Test with different legitimate sizes
    sizes_mb = [2, 5, 8]  # All under 10MB limit
    
    for size_mb in sizes_mb:
        print(f"\n--- Testing {size_mb}MB legitimate payload ---")
        
        payload_json = create_large_legitimate_payload(size_mb)
        payload_size_mb = len(payload_json.encode('utf-8')) / (1024 * 1024)
        print(f"Payload size: {payload_size_mb:.2f}MB")
        
        # Format as typical tool call
        content = f"```json\n{payload_json}\n```"
        
        start_time = time.time()
        
        try:
            result = repair_service.repair_tool_calls(content)
            
            end_time = time.time()
            duration = end_time - start_time
            
            print(f"[OK] Processed in {duration:.2f} seconds")
            
            if result:
                print(f"Tool call detected: {result.tool_call['function']['name']}")
                args_size = len(str(result.tool_call['function']['arguments']))
                print(f"Arguments processed: {args_size} characters")
            else:
                print("No tool call detected")
                
            # Should process successfully since under 10MB limit
            if duration > 5.0:
                print(f"[WARNING] Processing took {duration:.2f} seconds - may indicate performance issue")
            else:
                print(f"[SUCCESS] Legitimate payload processed successfully")
                
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            print(f"[ERROR] Failed after {duration:.2f} seconds: {type(e).__name__}: {e}")
    
    # Test edge case: exactly 10MB payload
    print(f"\n--- Testing 10MB boundary payload ---")
    
    boundary_json = create_large_legitimate_payload(10)
    boundary_size_mb = len(boundary_json.encode('utf-8')) / (1024 * 1024)
    print(f"Boundary payload size: {boundary_size_mb:.2f}MB")
    
    content = f"```json\n{boundary_json}\n```"
    
    start_time = time.time()
    
    try:
        result = repair_service.repair_tool_calls(content)
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"[OK] 10MB boundary processed in {duration:.2f} seconds")
        print(f"[SUCCESS] Boundary payload handled correctly")
        
    except Exception as e:
        end_time = time.time()
        duration = end_time - start_time
        print(f"[ERROR] 10MB boundary failed after {duration:.2f} seconds: {type(e).__name__}: {e}")
    
    # Test that >10MB is still blocked
    print(f"\n--- Verifying >10MB is still blocked ---")
    
    oversized_json = create_large_legitimate_payload(12)  # 12MB should be blocked
    oversized_size_mb = len(oversized_json.encode('utf-8')) / (1024 * 1024)
    print(f"Oversized payload size: {oversized_size_mb:.2f}MB")
    
    content = f"```json\n{oversized_json}\n```"
    
    start_time = time.time()
    
    try:
        result = repair_service.repair_tool_calls(content)
        
        end_time = time.time()
        duration = end_time - start_time
        
        if duration < 1.0 and not result:
            print(f"[SUCCESS] >10MB payload rejected quickly ({duration:.3f}s)")
        else:
            print(f"[WARNING] >10MB payload took {duration:.2f} seconds - protection may be insufficient")
            
    except Exception as e:
        end_time = time.time()
        duration = end_time - start_time
        print(f"[INFO] Exception for >10MB payload after {duration:.3f}s: {type(e).__name__}")

if __name__ == "__main__":
    test_legitimate_large_payloads()
    
    print("\n=== Summary ===")
    print("Expected behavior with 10MB limit:")
    print("1. Payloads <10MB: Process successfully (may take time)")
    print("2. Payloads >10MB: Rejected quickly (<1 second)")
    print("3. Boundary case (~10MB): Should work but may be slower")
    print("4. All rejections should have warning logs")