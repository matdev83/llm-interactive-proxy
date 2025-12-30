"""Script to remove outer try/except blocks from test_stages.py using AST parsing."""

import ast
import textwrap

# Read the original file
with open("src/core/app/stages/test_stages.py", "r", encoding="utf-8") as f:
    original_content = f.read()

# Parse the AST
tree = ast.parse(original_content)


def has_inner_try(node):
    """Check if a Try node has inner Try nodes within its body."""
    if not isinstance(node, ast.Try):
        return False
    for child in ast.walk(node):
        if child is not node and isinstance(child, ast.Try):
            return True
    return False


def remove_outer_try_except_from_function(func_node):
    """Remove outer try/except blocks from a function while keeping inner ones."""
    # Look for Try nodes at the top level of the function body
    new_body = []
    i = 0
    while i < len(func_node.body):
        stmt = func_node.body[i]
        if isinstance(stmt, ast.Try) and not has_inner_try(stmt):
            # This is an outer try/except without inner tries - remove the wrapper
            # Add the body content directly to new_body
            for try_stmt in stmt.body:
                new_body.append(try_stmt)
            # Skip the except/finally handlers
        elif isinstance(stmt, ast.Try) and has_inner_try(stmt):
            # This has inner try blocks - keep it as is
            new_body.append(stmt)
        else:
            new_body.append(stmt)
        i += 1

    func_node.body = new_body
    return func_node


# Find class definitions in the AST
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef):
        # Process methods in the class
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                # Remove try/except from specific methods
                method_name = item.name
                if method_name in [
                    "_override_session_service_for_test_compatibility",
                    "_register_backend_config_provider",
                    "_register_mock_backend_service",
                    "_register_mock_backend_factory",
                    "_register_backend_service",
                    "_register_mock_command_service",
                    "_register_mock_request_processor",
                ]:
                    remove_outer_try_except_from_function(item)


# Convert the modified AST back to source code
import astor

modified_content = astor.to_source(tree)

# Write the modified content back
with open("src/core/app/stages/test_stages.py", "w", encoding="utf-8") as f:
    f.write(modified_content)

print("Successfully removed outer try/except blocks from test_stages.py")
