#!/usr/bin/env python3
"""Analyze skipped tests and categorize them."""

import ast
import re
from pathlib import Path
from typing import Any

# Categories for skip reasons
LEGITIMATE_REASONS = {
    "windows-specific",
    "unix-specific",
    "platform-specific",
    "os-dependent",
    "authentication required",
    "credentials",
    "api key",
    "not installed",
    "not available",
    "not found",
    "file not found",
    "capture file",
    "wire captures",
    "symlinks not supported",
    "ipv6",
    "privilege checks",
    "runtime",
    "python runtime",
    "async generator",
    "timeout",
    "slow execution",
    "not yet implemented",
    "temporarily disabled",
    "permission issues",
}

SUSPICIOUS_REASONS = {
    "needs refactoring",
    "failing due to",
    "skipped by default",
    "not related to",
    "mocking issue",
    "thin facade",
    "phase 4",
}


def extract_skip_reason(node: ast.AST) -> str | None:
    """Extract skip reason from pytest.mark.skip or pytest.mark.skipif."""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in ("skip", "skipif"):
                # Look for reason= keyword argument
                for keyword in node.keywords:
                    if keyword.arg == "reason":
                        if isinstance(keyword.value, ast.Constant):
                            return keyword.value.value
                        elif isinstance(keyword.value, ast.Str):  # Python < 3.8
                            return keyword.value.s
    return None


def extract_skipif_condition(node: ast.AST) -> str | None:
    """Extract condition from pytest.mark.skipif."""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "skipif":
                # First positional argument is usually the condition
                if node.args:
                    # Try to get a string representation
                    try:
                        return ast.unparse(node.args[0]) if hasattr(ast, "unparse") else str(node.args[0])
                    except:
                        return str(node.args[0])
    return None


def analyze_test_file(file_path: Path) -> list[dict[str, Any]]:
    """Analyze a test file for skipped tests."""
    skipped_tests = []
    module_skip_reason = None
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content, filename=str(file_path))
    except Exception as e:
        return [{"error": f"Could not parse {file_path}: {e}"}]
    
    # Check for module-level skip (pytestmark = pytest.mark.skip(...))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "pytestmark":
                    if isinstance(node.value, ast.Call):
                        if isinstance(node.value.func, ast.Attribute):
                            if node.value.func.attr == "skip":
                                module_skip_reason = extract_skip_reason(node.value)
                            elif node.value.func.attr == "skipif":
                                module_skip_reason = extract_skip_reason(node.value)
                                skipif_cond = extract_skipif_condition(node.value)
                                if skipif_cond:
                                    module_skip_reason = f"{module_skip_reason or ''} (condition: {skipif_cond})"
    
    # Get all test functions (both sync and async)
    test_functions = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
    ]
    
    # If module is skipped, mark all tests
    if module_skip_reason:
        for node in test_functions:
            project_root = Path(__file__).parent
            try:
                rel_path = str(file_path.relative_to(project_root))
            except ValueError:
                rel_path = str(file_path)
            
            reason_lower = module_skip_reason.lower()
            is_suspicious = any(susp in reason_lower for susp in SUSPICIOUS_REASONS)
            is_legitimate = any(legit in reason_lower for legit in LEGITIMATE_REASONS)
            
            skipped_tests.append({
                "test_name": node.name,
                "file": rel_path,
                "reason": f"MODULE-LEVEL SKIP: {module_skip_reason}",
                "skipif_condition": None,
                "is_suspicious": is_suspicious,
                "is_legitimate": is_legitimate,
            })
        return skipped_tests
    
    for node in test_functions:
        # Check for decorators
        skip_reason = None
        skipif_condition = None
        is_skipped = False
        
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Attribute):
                    if decorator.func.attr == "skip":
                        skip_reason = extract_skip_reason(decorator)
                        is_skipped = True
                    elif decorator.func.attr == "skipif":
                        skipif_condition = extract_skipif_condition(decorator)
                        skip_reason = extract_skip_reason(decorator)
                        is_skipped = True
                elif isinstance(decorator.func, ast.Name):
                    if decorator.func.id == "skip":
                        is_skipped = True
        
        # Also check for pytest.skip() calls in the function body
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Call):
                if isinstance(stmt.func, ast.Attribute):
                    if stmt.func.attr == "skip":
                        is_skipped = True
                        # Try to extract reason from pytest.skip("reason")
                        if stmt.args and isinstance(stmt.args[0], (ast.Constant, ast.Str)):
                            skip_reason = stmt.args[0].value if isinstance(stmt.args[0], ast.Constant) else stmt.args[0].s
        
        if is_skipped:
            # Check if reason is suspicious
            reason_lower = (skip_reason or "").lower()
            is_suspicious = any(susp in reason_lower for susp in SUSPICIOUS_REASONS)
            is_legitimate = any(legit in reason_lower for legit in LEGITIMATE_REASONS)
            
            # Check skipif conditions for OS/platform checks
            if skipif_condition:
                cond_lower = skipif_condition.lower()
                if any(x in cond_lower for x in ["os.name", "platform.system", "windows", "unix", "nt"]):
                    is_legitimate = True
            
            # Get relative path from project root
            project_root = Path(__file__).parent
            try:
                rel_path = str(file_path.relative_to(project_root))
            except ValueError:
                rel_path = str(file_path)
            
            skipped_tests.append({
                "test_name": node.name,
                "file": rel_path,
                "reason": skip_reason,
                "skipif_condition": skipif_condition,
                "is_suspicious": is_suspicious,
                "is_legitimate": is_legitimate,
            })
    
    return skipped_tests


def main():
    """Main analysis function."""
    project_root = Path(__file__).parent
    tests_dir = project_root / "tests"
    all_skipped = []
    
    for test_file in tests_dir.rglob("test_*.py"):
        if test_file.is_file():
            skipped = analyze_test_file(test_file)
            all_skipped.extend(skipped)
    
    # Categorize
    suspicious = [t for t in all_skipped if t.get("is_suspicious") and not t.get("is_legitimate")]
    legitimate = [t for t in all_skipped if t.get("is_legitimate")]
    unclear = [t for t in all_skipped if not t.get("is_suspicious") and not t.get("is_legitimate")]
    
    print("=" * 80)
    print("SKIPPED TESTS ANALYSIS")
    print("=" * 80)
    print(f"\nTotal skipped tests found: {len(all_skipped)}")
    print(f"  - Suspicious (should be unskipped): {len(suspicious)}")
    print(f"  - Legitimate: {len(legitimate)}")
    print(f"  - Unclear: {len(unclear)}")
    
    print("\n" + "=" * 80)
    print("SUSPICIOUS TESTS (Should be unskipped):")
    print("=" * 80)
    for test in suspicious:
        print(f"\n{test['file']}::{test['test_name']}")
        if test['reason']:
            print(f"  Reason: {test['reason']}")
        if test['skipif_condition']:
            print(f"  Condition: {test['skipif_condition']}")
    
    if unclear:
        print("\n" + "=" * 80)
        print("UNCLEAR TESTS (Need manual review):")
        print("=" * 80)
        for test in unclear[:20]:  # Limit to first 20
            print(f"\n{test['file']}::{test['test_name']}")
            if test['reason']:
                print(f"  Reason: {test['reason']}")
            if test['skipif_condition']:
                print(f"  Condition: {test['skipif_condition']}")


if __name__ == "__main__":
    main()
