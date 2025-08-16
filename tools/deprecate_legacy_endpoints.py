#!/usr/bin/env python3
"""
Legacy Endpoint Deprecation Tool

This script helps to identify and deprecate legacy API endpoints by:
1. Adding deprecation warnings to responses
2. Logging deprecation usage
3. Setting up feature flags to control switchover
"""

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Deprecate legacy API endpoints")
    parser.add_argument(
        "--list",
        action="store_true",
        help="List detected legacy endpoints",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deprecation warnings to legacy endpoints",
    )
    parser.add_argument(
        "--sunset-date",
        type=str,
        default=(datetime.now().replace(month=datetime.now().month + 3)).strftime("%Y-%m-%d"),
        help="Sunset date for legacy endpoints (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--base-path",
        type=str,
        default="src",
        help="Base path for code search",
    )
    return parser.parse_args()


def find_legacy_endpoints(base_path: str) -> List[Dict[str, str]]:
    """Find legacy API endpoints in the codebase.
    
    Args:
        base_path: Path to search
        
    Returns:
        List of detected endpoints with metadata
    """
    endpoints = []
    
    # Patterns to look for
    route_patterns = [
        r"@app\.(?:get|post|put|delete|patch)\(['\"](.+?)['\"]\)",
        r"app\.route\(['\"](.+?)['\"].*methods=\[['\"](GET|POST|PUT|DELETE|PATCH)['\"]",
    ]
    
    # Skip new versioned endpoints
    skip_patterns = [
        r"/v\d+/",
        r"^/v2/",
        r"^/docs",
        r"^/openapi",
        r"^/redoc",
    ]
    
    # Walk the directory
    for root, _, files in os.walk(base_path):
        for file in files:
            if not file.endswith(".py"):
                continue
                
            file_path = os.path.join(root, file)
            
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    
                    # Look for route definitions
                    for pattern in route_patterns:
                        matches = re.finditer(pattern, content)
                        for match in matches:
                            route = match.group(1)
                            
                            # Skip if new versioned endpoint or docs
                            if any(re.search(skip, route) for skip in skip_patterns):
                                continue
                                
                            # Add to endpoints
                            endpoints.append({
                                "route": route,
                                "file": file_path,
                                "line": content[:match.start()].count("\n") + 1,
                                "versioned_route": f"/v1{route}" if not route.startswith("/v1/") else route
                            })
                            
            except Exception as e:
                print(f"Error processing {file_path}: {e}")
    
    return endpoints


def apply_deprecation_warnings(endpoints: List[Dict[str, str]], sunset_date: str) -> None:
    """Apply deprecation warnings to legacy endpoints.
    
    Args:
        endpoints: List of endpoints to deprecate
        sunset_date: Sunset date string (YYYY-MM-DD)
    """
    for endpoint in endpoints:
        try:
            # Read the file
            with open(endpoint["file"], "r", encoding="utf-8") as f:
                content = f.readlines()
                
            # Line where the endpoint is defined
            line_num = endpoint["line"] - 1
            
            # Check if deprecation has already been applied
            if line_num < len(content) and "DEPRECATED" in content[line_num]:
                print(f"Skipping already deprecated endpoint: {endpoint['route']}")
                continue
                
            # Look for the response section
            response_line = -1
            for i in range(line_num, min(line_num + 50, len(content))):
                if "return " in content[i] and (
                    "Response" in content[i] or 
                    "JSONResponse" in content[i] or
                    "return {" in content[i]
                ):
                    response_line = i
                    break
                    
            if response_line == -1:
                print(f"Could not find response for endpoint {endpoint['route']}")
                continue
                
            # Add deprecation warning
            indentation = len(content[response_line]) - len(content[response_line].lstrip())
            indent = " " * indentation
            
            # Determine how to add warning based on the response style
            if "return {" in content[response_line] or "return json" in content[response_line].lower():
                # JSON response - add warning to the dict
                new_response_line = (
                    f"{indent}# DEPRECATED: This endpoint will be removed on {sunset_date}\n"
                    f"{indent}response_data = {content[response_line].strip('return ').strip()}\n"
                    f"{indent}if isinstance(response_data, dict):\n"
                    f"{indent}    response_data['deprecated'] = True\n"
                    f"{indent}    response_data['sunset_date'] = '{sunset_date}'\n"
                    f"{indent}return response_data\n"
                )
                
                # Replace the original line
                content[response_line] = f"{indent}# Original: {content[response_line].strip()}\n"
                content.insert(response_line + 1, new_response_line)
                
            else:
                # Response object - add warning header
                warning_lines = [
                    f"{indent}# DEPRECATED: This endpoint will be removed on {sunset_date}\n",
                    f"{indent}response = {content[response_line].strip('return ').strip()}\n",
                    f"{indent}response.headers['Deprecation'] = 'true'\n",
                    f"{indent}response.headers['Sunset'] = '{sunset_date}'\n",
                    f"{indent}return response\n"
                ]
                
                # Replace the original line
                content[response_line] = f"{indent}# Original: {content[response_line].strip()}\n"
                for i, line in enumerate(warning_lines):
                    content.insert(response_line + 1 + i, line)
                
            # Write the file back
            with open(endpoint["file"], "w", encoding="utf-8") as f:
                f.writelines(content)
                
            print(f"Applied deprecation warning to {endpoint['route']} in {endpoint['file']}")
            
        except Exception as e:
            print(f"Error applying deprecation warning to {endpoint['route']}: {e}")


def main() -> None:
    """Main function."""
    args = parse_args()
    
    print("Searching for legacy endpoints...")
    endpoints = find_legacy_endpoints(args.base_path)
    
    if not endpoints:
        print("No legacy endpoints found.")
        return
        
    print(f"Found {len(endpoints)} legacy endpoints:")
    for endpoint in endpoints:
        print(f"  {endpoint['route']} in {endpoint['file']}:{endpoint['line']}")
        
    if args.apply:
        print(f"\nApplying deprecation warnings with sunset date {args.sunset_date}...")
        apply_deprecation_warnings(endpoints, args.sunset_date)
        print("Done!")
    else:
        print("\nRun with --apply to add deprecation warnings to these endpoints.")


if __name__ == "__main__":
    main()

