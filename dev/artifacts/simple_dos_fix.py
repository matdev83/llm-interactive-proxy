#!/usr/bin/env python3
"""
Very targeted fix for DoS vulnerability - just add size checks before json.loads calls
"""
import re

def fix_dos_vulnerability():
    file_path = r"C:\Users\Mateusz\source\repos\llm-interactive-proxy\src\connectors\antigravity_oauth.py"
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace each vulnerable json.loads call with a protected version
    # First one around line 280
    content = re.sub(
        r'(\s+)(tools_data = json\.loads\(tool_json\))',
        r'\1# DoS protection: Size check (10MB limit)\n\1if len(tool_json.encode("utf-8")) > 10485760:\n\1    return None\n\1\2',
        content,
        count=1
    )
    
    # Second one around line 380  
    content = re.sub(
        r'(\s+)(tools_data = json\.loads\(tool_json\))',
        r'\1# DoS protection: Size check (10MB limit)\n\1if len(tool_json.encode("utf-8")) > 10485760:\n\1    break\n\1\2',
        content,
        count=1
    )
    
    # Third one around line 1057
    content = re.sub(
        r'(\s+)(auth_data = json\.loads\(raw_value_str\))',
        r'\1# DoS protection: Size check (10MB limit)\n\1if len(raw_value_str.encode("utf-8")) > 10485760:\n\1    return None\n\1\2',
        content,
        count=1
    )
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("Applied DoS protection fixes!")

if __name__ == "__main__":
    fix_dos_vulnerability()