#!/usr/bin/env python3
"""
Pre-commit hook to check for architectural violations.

This script runs before commits to catch SOLID violations early.
"""

import subprocess
import sys
from pathlib import Path


def run_architectural_linter(files):
    """Run the architectural linter on changed files."""
    if not files:
        return True
    
    # Filter for Python files in domain and services directories
    relevant_files = [
        f for f in files 
        if f.endswith('.py') and 
        any(path in f for path in ['/domain/', '/services/', '/core/'])
    ]
    
    if not relevant_files:
        return True
    
    print("[ARCH] Running architectural linter on changed files...")
    
    # Run the linter
    linter_path = Path(__file__).parent.parent / "tools" / "architectural_linter.py"
    
    violations_found = False
    for file_path in relevant_files:
        try:
            result = subprocess.run(
                [sys.executable, str(linter_path), file_path],
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                violations_found = True
                print(f"\n[ERROR] Violations found in {file_path}:")
                print(result.stdout)
                if result.stderr:
                    print("Errors:", result.stderr)
        
        except Exception as e:
            print(f"Error running linter on {file_path}: {e}")
            return False
    
    if violations_found:
        print("\n" + "="*60)
        print("[BLOCKED] COMMIT BLOCKED: Architectural violations detected!")
        print("Please fix the violations above before committing.")
        print("="*60)
        return False
    
    print("[OK] No architectural violations found!")
    return True


def check_imports():
    """Check for problematic imports in domain layer."""
    domain_files = list(Path("src/core/domain").rglob("*.py"))
    
    violations = []
    
    for file_path in domain_files:
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Check for web framework imports
            problematic_imports = [
                'from fastapi',
                'import fastapi',
                'from flask',
                'import flask',
                'from django',
                'import django'
            ]
            
            for line_num, line in enumerate(content.split('\n'), 1):
                for bad_import in problematic_imports:
                    if bad_import in line.lower():
                        violations.append(f"{file_path}:{line_num}: Domain layer imports web framework: {line.strip()}")
        
        except Exception:
            continue
    
    if violations:
        print("\n[ERROR] Web framework imports found in domain layer:")
        for violation in violations:
            print(f"  {violation}")
        return False
    
    return True


def main():
    """Main entry point for pre-commit hook."""
    # Get list of staged files
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True
        )
        staged_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        print("Error: Could not get staged files from git")
        return 1
    
    success = True
    
    # Run architectural linter
    if not run_architectural_linter(staged_files):
        success = False
    
    # Check imports
    if not check_imports():
        success = False
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())