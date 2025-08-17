#!/usr/bin/env python
"""
Trace Import Dependencies

This script analyzes import dependencies in the codebase, creating a dependency graph
that shows which modules import which other modules. It's particularly useful for
identifying dependencies on legacy code that needs to be migrated.
"""

import ast
import os
import sys
from collections import defaultdict
from pathlib import Path


class ImportVisitor(ast.NodeVisitor):
    """AST visitor that finds imports."""
    
    def __init__(self):
        self.imports = []
        
    def visit_Import(self, node):
        """Visit Import nodes."""
        for name in node.names:
            self.imports.append((name.name, name.asname))
        self.generic_visit(node)
        
    def visit_ImportFrom(self, node):
        """Visit ImportFrom nodes."""
        if node.module is not None:  # Ignore relative imports with no module
            for name in node.names:
                if node.level == 0:  # Absolute import
                    self.imports.append((f"{node.module}.{name.name}", name.asname))
                else:  # Relative import
                    self.imports.append((f"relative.{node.level}.{node.module}.{name.name}", name.asname))
        self.generic_visit(node)


def find_imports(file_path: Path) -> list[tuple[str, str | None]]:
    """Find imports in a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        List of (imported_module, alias) tuples
    """
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()
            
        tree = ast.parse(content)
        visitor = ImportVisitor()
        visitor.visit(tree)
        
        return visitor.imports
    except SyntaxError:
        print(f"Error parsing {file_path}")
        return []
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return []


def is_legacy_module(module_name: str, legacy_prefixes: list[str]) -> bool:
    """Check if a module is a legacy module.
    
    Args:
        module_name: Name of the module
        legacy_prefixes: List of prefixes for legacy modules
        
    Returns:
        True if the module is a legacy module
    """
    return any(module_name.startswith(prefix) for prefix in legacy_prefixes)


def analyze_imports(
    directory: str | Path, 
    legacy_prefixes: list[str] = ['src.proxy_logic', 'src.command_parser', 'src.command_processor', 'src.session']
) -> dict[str, list[str]]:
    """Analyze imports in a directory.
    
    Args:
        directory: Directory to analyze
        legacy_prefixes: List of prefixes for legacy modules
        
    Returns:
        Dictionary mapping module paths to lists of imported legacy modules
    """
    dependencies = {}
    directory_path = Path(directory)
    
    for path in directory_path.rglob('*.py'):
        if path.is_file():
            # Convert to module path
            rel_path = path.relative_to(directory_path.parent)
            module_path = str(rel_path).replace(os.sep, '.')[:-3]  # Remove .py extension
            
            # Find imports
            imports = find_imports(path)
            legacy_imports = [imp for imp, _ in imports if is_legacy_module(imp, legacy_prefixes)]
            
            if legacy_imports:
                dependencies[module_path] = legacy_imports
    
    return dependencies


def build_dependency_graph(dependencies: dict[str, list[str]]) -> dict[str, set[str]]:
    """Build a dependency graph.
    
    Args:
        dependencies: Dictionary mapping module paths to lists of imported modules
        
    Returns:
        Dictionary mapping modules to sets of modules that depend on them
    """
    graph = defaultdict(set)
    
    for module, imports in dependencies.items():
        for imported in imports:
            graph[imported].add(module)
    
    return graph


def print_dependency_graph(graph: dict[str, set[str]]) -> None:
    """Print the dependency graph.
    
    Args:
        graph: Dictionary mapping modules to sets of modules that depend on them
    """
    if not graph:
        print("No dependencies found.")
        return
    
    print("Dependency Graph:")
    print("----------------")
    
    for module, dependents in sorted(graph.items()):
        print(f"\n{module} is imported by:")
        for dependent in sorted(dependents):
            print(f"  - {dependent}")


def generate_markdown_report(dependencies: dict[str, list[str]], graph: dict[str, set[str]]) -> str:
    """Generate a markdown report of the dependency graph.
    
    Args:
        dependencies: Dictionary mapping module paths to lists of imported modules
        graph: Dictionary mapping modules to sets of modules that depend on them
        
    Returns:
        Markdown report
    """
    lines = ["# Import Dependencies Report\n"]
    
    # Modules with legacy imports
    lines.append("## Modules with Legacy Imports\n")
    
    if not dependencies:
        lines.append("No modules with legacy imports found.\n")
    else:
        lines.append("| Module | Legacy Imports |")
        lines.append("|--------|---------------|")
        
        for module, imports in sorted(dependencies.items()):
            imports_str = "<br>".join(sorted(imports))
            lines.append(f"| {module} | {imports_str} |")
    
    # Legacy modules and their dependents
    lines.append("\n## Legacy Modules and Their Dependents\n")
    
    if not graph:
        lines.append("No legacy module dependencies found.\n")
    else:
        lines.append("| Legacy Module | Dependent Modules |")
        lines.append("|--------------|------------------|")
        
        for module, dependents in sorted(graph.items()):
            dependents_str = "<br>".join(sorted(dependents))
            lines.append(f"| {module} | {dependents_str} |")
    
    # Summary of dependencies
    lines.append("\n## Summary\n")
    
    # Count of modules with legacy imports
    lines.append(f"- **Modules with Legacy Imports**: {len(dependencies)}")
    
    # Count of legacy modules
    lines.append(f"- **Legacy Modules with Dependents**: {len(graph)}")
    
    # Most imported legacy module
    if graph:
        most_imported = max(graph.items(), key=lambda x: len(x[1]))
        lines.append(f"- **Most Imported Legacy Module**: {most_imported[0]} (imported by {len(most_imported[1])} modules)")
    
    return "\n".join(lines)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python trace_imports.py DIRECTORY [LEGACY_PREFIXES...]")
        print("Example: python trace_imports.py src src.proxy_logic src.command_parser")
        sys.exit(1)
        
    directory = sys.argv[1]
    legacy_prefixes = sys.argv[2:] if len(sys.argv) > 2 else [
        'src.proxy_logic', 
        'src.command_parser', 
        'src.command_processor', 
        'src.session'
    ]
    
    print(f"Analyzing imports in {directory}...")
    print(f"Looking for imports of modules with these prefixes: {legacy_prefixes}")
    
    dependencies = analyze_imports(directory, legacy_prefixes)
    graph = build_dependency_graph(dependencies)
    
    print_dependency_graph(graph)
    
    # Generate markdown report
    report = generate_markdown_report(dependencies, graph)
    
    # Write report to file
    report_path = Path("dev/import_dependencies_report.md")
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    main()
