#!/usr/bin/env python3
"""Analyze tool schemas in CBOR capture to find JSON Schema draft issues."""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.simulation.capture_reader import CaptureReader


def analyze_tool_schemas(cbor_file: str):
    """Extract and analyze tool schemas from CBOR capture."""
    reader = CaptureReader()
    session = reader.load(cbor_file)
    
    print(f"Analyzing {len(session.entries)} entries...")
    
    for idx, entry in enumerate(session.entries):
        # Direction 2 = PROXY_TO_BACKEND
        if entry.direction == 2 and entry.data:
            try:
                # Data might be bytes
                if isinstance(entry.data, bytes):
                    data = json.loads(entry.data.decode('utf-8'))
                elif isinstance(entry.data, str):
                    data = json.loads(entry.data)
                else:
                    data = entry.data
                
                if "tools" in data:
                    print(f"\n{'='*70}")
                    print(f"Entry [{idx}] - Found {len(data['tools'])} tools")
                    print(f"{'='*70}")
                    
                    for tool_idx, tool in enumerate(data["tools"]):
                        tool_name = tool.get('name', tool.get('function', {}).get('name', 'unnamed'))
                        print(f"\nTool {tool_idx}: {tool_name}")
                        print(f"  Tool keys: {list(tool.keys())}")
                        
                        # Check for input_schema (direct)
                        if "input_schema" in tool:
                            schema = tool["input_schema"]
                            print(f"  Has input_schema: {type(schema)}")
                            
                            # Check for JSON Schema draft version
                            if "$schema" in schema:
                                print(f"  $schema: {schema['$schema']}")
                            else:
                                print(f"  WARNING: No $schema field!")
                            
                            # Check for problematic fields
                            if "additionalProperties" in schema:
                                print(f"  additionalProperties: {schema['additionalProperties']}")
                            
                            # Print full schema for tool 9 (the problematic one)
                            if tool_idx == 9:
                                print(f"\n  FULL SCHEMA FOR TOOL 9:")
                                print(json.dumps(schema, indent=2))
                        
                        # Check for function.parameters (OpenAI format)
                        if "function" in tool and "parameters" in tool["function"]:
                            schema = tool["function"]["parameters"]
                            print(f"  Has function.parameters: {type(schema)}")
                            
                            if "$schema" in schema:
                                print(f"  $schema: {schema['$schema']}")
                            else:
                                print(f"  WARNING: No $schema field in function.parameters!")
                            
                            if tool_idx == 9:
                                print(f"\n  FULL FUNCTION.PARAMETERS FOR TOOL 9:")
                                print(json.dumps(schema, indent=2))
                        
                        # Check for custom field (Anthropic format)
                        if "custom" in tool:
                            custom = tool["custom"]
                            print(f"  Has custom field with keys: {list(custom.keys())}")
                            if "input_schema" in custom:
                                schema = custom["input_schema"]
                                print(f"  Has custom.input_schema: {type(schema)}")
                                
                                if "$schema" in schema:
                                    print(f"  $schema: {schema['$schema']}")
                                else:
                                    print(f"  WARNING: No $schema field in custom.input_schema!")
                                
                                # Print full schema for tool 9
                                if tool_idx == 9:
                                    print(f"\n  FULL CUSTOM.INPUT_SCHEMA FOR TOOL 9:")
                                    print(json.dumps(schema, indent=2))
                    
                    # Only analyze first request with tools
                    break
                    
            except Exception as e:
                print(f"Error processing entry {idx}: {e}")
                continue


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyze_tool_schema.py <cbor_file>")
        sys.exit(1)
    
    analyze_tool_schemas(sys.argv[1])
