#!/usr/bin/env python3
"""
Script to run the exception hygiene linter and output all findings.
This is a wrapper around the linter test to make it easier to run.
"""

import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Import the linter function from the test file
# We'll execute the test code directly
import ast
from typing import List, NamedTuple

class Finding(NamedTuple):
    """Represents a single exception hygiene finding."""
    code: str
    message: str
    filename: str
    lineno: int
    col_offset: int


def _find_exception_hygiene_issues(code: str, filename: str) -> List[Finding]:
    """
    Find exception hygiene issues in the given code.
    This is copied from the test file to avoid importing test code.
    """
    findings = []
    
    try:
        tree = ast.parse(code, filename=filename)
    except SyntaxError:
        return findings
    
    # Visitor for EXH001: Missing exc_info in logger calls
    class _MissingExcInfoVisitor(ast.NodeVisitor):
        def __init__(self):
            self.findings = []
            self._exception_handler_depth = 0
            self._suppressed_lines = set()
            
        def _is_inside_exception_handler(self):
            return self._exception_handler_depth > 0
            
        def _is_logger_call(self, node):
            """Check if node is a logger.error/warning call."""
            if not isinstance(node, ast.Call):
                return False
            if not isinstance(node.func, ast.Attribute):
                return False
            if node.func.attr not in ('error', 'warning'):
                return False
            return True
            
        def _has_exc_info_kwarg(self, node):
            """Check if call has exc_info keyword argument."""
            for keyword in node.keywords:
                if keyword.arg == 'exc_info':
                    return True
            return False
            
        def _is_logger_exception_call(self, node):
            """Check if node is a logger.exception() call."""
            if not isinstance(node, ast.Call):
                return False
            if not isinstance(node.func, ast.Attribute):
                return False
            return node.func.attr == 'exception'
            
        def visit_ExceptHandler(self, node):
            self._exception_handler_depth += 1
            self.generic_visit(node)
            self._exception_handler_depth -= 1
            
        def visit_Expr(self, node):
            if self._is_inside_exception_handler():
                if isinstance(node.value, ast.Call):
                    call = node.value
                    if self._is_logger_call(call):
                        if not self._has_exc_info_kwarg(call):
                            if not self._is_logger_exception_call(call):
                                if node.lineno not in self._suppressed_lines:
                                    self.findings.append(Finding(
                                        code='EXH001',
                                        message='Missing exc_info=True in logger call within exception handler',
                                        filename=filename,
                                        lineno=node.lineno,
                                        col_offset=node.col_offset
                                    ))
            self.generic_visit(node)
    
    # Visitor for EXH003: Silent exception handlers
    class _SilentExceptionHandlerVisitor(ast.NodeVisitor):
        def __init__(self):
            self.findings = []
            self._suppressed_lines = set()
            
        def _is_cleanup_context(self, node):
            """Check if we're in a cleanup method that's allowed to be silent."""
            # Walk up to find if we're in __exit__, __del__, close(), etc.
            return False  # Simplified for now
            
        def _handler_reraises(self, handler):
            """Check if handler contains a raise statement."""
            for stmt in ast.walk(handler):
                if isinstance(stmt, ast.Raise):
                    return True
            return False
            
        def _is_control_flow_exception(self, handler):
            """Check if handler catches control flow exceptions."""
            if handler.type is None:
                return False
            if isinstance(handler.type, ast.Name):
                return handler.type.id in ('StopIteration', 'ImportError', 'JSONDecodeError', 
                                          'KeyError', 'AttributeError')
            return False
            
        def visit_ExceptHandler(self, node):
            # Check if handler is silent (just 'pass')
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                if not self._handler_reraises(node):
                    if not self._is_control_flow_exception(node):
                        if node.lineno not in self._suppressed_lines:
                            self.findings.append(Finding(
                                code='EXH003',
                                message='Silent exception handler (except: pass) with no logging',
                                filename=filename,
                                lineno=node.lineno,
                                col_offset=node.col_offset
                            ))
            self.generic_visit(node)
    
    # Visitor for EXH004: Incorrect exc_info usage
    class _IncorrectExcInfoUsageVisitor(ast.NodeVisitor):
        def __init__(self):
            self.findings = []
            self._suppressed_lines = set()
            
        def visit_Call(self, node):
            # Check for exc_info=e instead of exc_info=True
            for keyword in node.keywords:
                if keyword.arg == 'exc_info':
                    # exc_info should be True, not a variable
                    if isinstance(keyword.value, ast.Name):
                        if node.lineno not in self._suppressed_lines:
                            self.findings.append(Finding(
                                code='EXH004',
                                message=f'Incorrect exc_info usage: exc_info={keyword.value.id} (should be exc_info=True)',
                                filename=filename,
                                lineno=node.lineno,
                                col_offset=node.col_offset
                            ))
            self.generic_visit(node)
    
    # Parse suppression comments
    suppressed_lines = set()
    for lineno, line in enumerate(code.split('\n'), start=1):
        if '# exception-hygiene: ignore=' in line:
            suppressed_lines.add(lineno + 1)  # Suppress next line
    
    # Run visitors
    visitor1 = _MissingExcInfoVisitor()
    # Type: ignore for protected access - this is an internal test script
    visitor1._suppressed_lines = suppressed_lines  # type: ignore[attr-defined]
    visitor1.visit(tree)
    findings.extend(visitor1.findings)
    
    visitor3 = _SilentExceptionHandlerVisitor()
    visitor3._suppressed_lines = suppressed_lines  # type: ignore[attr-defined]
    visitor3.visit(tree)
    findings.extend(visitor3.findings)
    
    visitor4 = _IncorrectExcInfoUsageVisitor()
    visitor4._suppressed_lines = suppressed_lines  # type: ignore[attr-defined]
    visitor4.visit(tree)
    findings.extend(visitor4.findings)
    
    return findings


def main():
    """Run the linter on all Python files in src/."""
    src_dir = project_root / "src"
    all_findings = []
    
    # Scan all Python files
    for py_file in src_dir.rglob("*.py"):
        try:
            code = py_file.read_text(encoding='utf-8')
            findings = _find_exception_hygiene_issues(code, str(py_file))
            all_findings.extend(findings)
        except Exception as e:
            print(f"Error scanning {py_file}: {e}", file=sys.stderr)
    
    # Sort by code, then filename, then line number
    all_findings.sort(key=lambda f: (f.code, f.filename, f.lineno))
    
    # Group by code
    by_code = {}
    for finding in all_findings:
        if finding.code not in by_code:
            by_code[finding.code] = []
        by_code[finding.code].append(finding)
    
    # Print summary
    print(f"Exception Hygiene Linter Results")
    print(f"=" * 80)
    print(f"Total findings: {len(all_findings)}")
    print()
    
    for code in sorted(by_code.keys()):
        findings = by_code[code]
        print(f"{code}: {len(findings)} findings")
    print()
    
    # Print detailed findings
    print(f"Detailed Findings")
    print(f"=" * 80)
    
    for code in sorted(by_code.keys()):
        findings = by_code[code]
        print(f"\n{code} ({len(findings)} findings):")
        print("-" * 80)
        for i, finding in enumerate(findings, 1):
            rel_path = Path(finding.filename).relative_to(project_root)
            print(f"{i}. {rel_path}:{finding.lineno}")
            print(f"   {finding.message}")
    
    # Write JSON output for orchestration
    output_file = project_root / "dev" / "artifacts" / "exception_hygiene_findings.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    findings_data = [
        {
            'code': f.code,
            'message': f.message,
            'filename': str(Path(f.filename).relative_to(project_root)),
            'lineno': f.lineno,
            'col_offset': f.col_offset
        }
        for f in all_findings
    ]
    
    output_file.write_text(json.dumps(findings_data, indent=2), encoding='utf-8')
    print(f"\n\nJSON output written to: {output_file}")
    
    return 0 if len(all_findings) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
