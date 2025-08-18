"""Debug version of command parsing to see what's happening."""

import re

def debug_command_parsing():
    """Debug command parsing logic."""
    content = "!/model(name=gpt-4)"
    
    print(f"Content: {content}")
    
    # Test the correct pattern
    pattern = r"!/(\w+)\(([^)]*)\)"
    print(f"Pattern: {pattern}")
    match = re.match(pattern, content)
    if match:
        cmd_name = match.group(1)
        args_str = match.group(2)
        print(f"  Command name: {cmd_name}")
        print(f"  Args string: {args_str}")
    else:
        print("  No match found")

if __name__ == "__main__":
    debug_command_parsing()