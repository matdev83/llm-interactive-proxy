#!/usr/bin/env python3
"""
Surgical fix for DoS vulnerability in antigravity_oauth.py
This script will add size validation to vulnerable json.loads calls
"""
import re

def fix_dos_vulnerability():
    file_path = r"C:\Users\Mateusz\source\repos\llm-interactive-proxy\src\connectors\antigravity_oauth.py"
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Add constant after logger line
    content = re.sub(
        r'(logger = logging\.getLogger\(__name__\))',
        r'\1\n\n# Maximum JSON parse size to prevent DoS attacks (10MB)\nMAX_JSON_PARSE_SIZE = 10 * 1024 * 1024',
        content
    )
    
    # Fix first vulnerability at line ~280
    content = re.sub(
        r'(\s+)(tools_data = json\.loads\(tool_json\))',
        r'\1# DoS protection: Check JSON size before parsing\n\1if len(tool_json.encode("utf-8")) > MAX_JSON_PARSE_SIZE:\n\1    if logger.isEnabledFor(logging.WARNING):\n\1        logger.warning(\n\1            "Tool JSON too large for parsing (%d bytes, limit: %d bytes)",\n\1            len(tool_json.encode("utf-8")),\n\1            MAX_JSON_PARSE_SIZE,\n\1        )\n\1    return None\n\1\2',
        content,
        count=1
    )
    
    # Fix second vulnerability at line ~380  
    content = re.sub(
        r'(\s+)(tools_data = json\.loads\(tool_json\))',
        r'\1# DoS protection: Check JSON size before parsing\n\1if len(tool_json.encode("utf-8")) > MAX_JSON_PARSE_SIZE:\n\1    if logger.isEnabledFor(logging.WARNING):\n\1        logger.warning(\n\1            "Streaming tool JSON too large for parsing (%d bytes, limit: %d bytes)",\n\1            len(tool_json.encode("utf-8")),\n\1            MAX_JSON_PARSE_SIZE,\n\1        )\n\1    break\n\1\2',
        content,
        count=1
    )
    
    # Fix third vulnerability at line ~1057
    content = re.sub(
        r'(\s+)(auth_data = json\.loads\(raw_value_str\))',
        r'\1# DoS protection: Check JSON size before parsing\n\1if len(raw_value_str.encode("utf-8")) > MAX_JSON_PARSE_SIZE:\n\1    if logger.isEnabledFor(logging.WARNING):\n\1        logger.warning(\n\1            "Auth status JSON too large for parsing (%d bytes, limit: %d bytes)",\n\1            len(raw_value_str.encode("utf-8")),\n\1            MAX_JSON_PARSE_SIZE,\n\1        )\n\1    return None\n\1\2',
        content,
        count=1
    )
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("DoS vulnerability fixes applied successfully!")

if __name__ == "__main__":
    fix_dos_vulnerability()