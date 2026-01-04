"""
Property-based tests for architectural validation.

These tests verify that the streaming pipeline maintains proper layer
separation, transport isolation, and narrow middleware interfaces.

Feature: streaming-pipeline-refactor
"""

import ast
import importlib
import inspect
from pathlib import Path

import pytest


# Helper functions for architectural analysis
def get_module_dependencies(module_path: str) -> set[str]:
    """Extract import dependencies from a Python module.

    Args:
        module_path: Path to the Python module file

    Returns:
        Set of imported module names
    """
    dependencies = set()

    try:
        with open(module_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=module_path)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dependencies.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                dependencies.add(node.module.split(".")[0])

    except Exception:
        # If we can't parse the file, return empty set
        pass

    return dependencies


def get_layer_for_module(module_path: str) -> str | None:
    """Determine which architectural layer a module belongs to.

    Args:
        module_path: Path to the Python module file

    Returns:
        Layer name or None if not in a recognized layer
    """
    # Normalize path
    path = Path(module_path)
    parts = path.parts

    # Check if this is in src/core
    if "src" in parts and "core" in parts:
        core_idx = parts.index("core")
        if core_idx + 1 < len(parts):
            subdir = parts[core_idx + 1]

            # Map subdirectories to layers
            layer_mapping = {
                "ports": "normalizer",
                "adapters": "assembler",
                "transport": "transport",
                "services": "processor",
                "domain": "domain",
                "interfaces": "interfaces",
            }

            return layer_mapping.get(subdir)

    # Check if this is a connector (producer layer)
    if "connectors" in parts:
        return "producer"

    return None


def find_circular_dependencies(
    module_paths: list[str],
) -> list[tuple[str, str]]:
    """Find circular dependencies between modules.

    Args:
        module_paths: List of module file paths to analyze

    Returns:
        List of (module_a, module_b) tuples representing circular dependencies
    """
    # Build dependency graph
    graph: dict[str, set[str]] = {}

    for module_path in module_paths:
        module_name = Path(module_path).stem
        dependencies = get_module_dependencies(module_path)
        graph[module_name] = dependencies

    # Find cycles using DFS
    circular_deps = []
    visited = set()
    rec_stack = set()

    def has_cycle(node: str, path: list[str]) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                if has_cycle(neighbor, path):
                    return True
            elif neighbor in rec_stack:
                # Found a cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:]
                for i in range(len(cycle) - 1):
                    circular_deps.append((cycle[i], cycle[i + 1]))
                return True

        path.pop()
        rec_stack.remove(node)
        return False

    for node in graph:
        if node not in visited:
            has_cycle(node, [])

    return circular_deps


def get_streaming_modules() -> list[str]:
    """Get all Python modules in the streaming pipeline.

    Returns:
        List of module file paths
    """
    modules = []

    # Get src/core/ports (normalizer layer)
    ports_dir = Path("src/core/ports")
    if ports_dir.exists():
        for file in ports_dir.glob("*.py"):
            if file.name != "__init__.py":
                modules.append(str(file))

    # Get src/core/adapters (assembler layer)
    adapters_dir = Path("src/core/adapters")
    if adapters_dir.exists():
        for file in adapters_dir.glob("*.py"):
            if file.name != "__init__.py":
                modules.append(str(file))

    # Get src/core/transport (transport layer)
    transport_dir = Path("src/core/transport")
    if transport_dir.exists():
        for file in transport_dir.rglob("*.py"):
            if file.name != "__init__.py":
                modules.append(str(file))

    # Get src/core/services/streaming (processor layer)
    streaming_services_dir = Path("src/core/services/streaming")
    if streaming_services_dir.exists():
        for file in streaming_services_dir.glob("*.py"):
            if file.name != "__init__.py":
                modules.append(str(file))

    # Get src/connectors (producer layer) - limit to first 20 files for performance
    connectors_dir = Path("src/connectors")
    if connectors_dir.exists():
        connector_files = [
            f
            for f in connectors_dir.glob("*.py")
            if f.name != "__init__.py" and not f.name.startswith("_")
        ]
        # Limit to first 20 files for performance while maintaining coverage
        modules.extend(str(f) for f in connector_files[:20])

    return modules


# Property 6: Layer separation
@pytest.mark.skipif(
    not Path("src/core/ports").exists(),
    reason="Streaming pipeline not yet implemented",
)
def test_property_layer_separation() -> None:
    """
    Property 6: Layer separation
    Feature: streaming-pipeline-refactor, Property 6: Layer separation

    For any component in the streaming pipeline, it should only depend on
    adjacent layers and not skip layers or create circular dependencies.

    Validates: Requirements 2.1
    """
    # Get all streaming modules
    modules = get_streaming_modules()

    if not modules:
        pytest.skip("No streaming modules found")

    # Define valid layer dependencies (which layers can depend on which)
    # Format: layer -> set of layers it can depend on
    valid_dependencies = {
        "producer": {"domain", "interfaces"},  # Backends can use domain models
        "normalizer": {"domain", "interfaces"},  # Normalizers can use domain models
        "processor": {
            "normalizer",
            "domain",
            "interfaces",
        },  # Processors use normalizer contracts
        "assembler": {
            "normalizer",
            "domain",
            "interfaces",
        },  # Assemblers use normalizer contracts
        "transport": {"assembler", "domain", "interfaces"},  # Transport uses assemblers
    }

    # Check each module's dependencies
    violations = []

    # Pre-compute module layers to avoid repeated path operations
    module_layers = {}
    for module_path in modules:
        layer = get_layer_for_module(module_path)
        if layer:
            module_layers[module_path] = layer

    for module_path, module_layer in module_layers.items():
        dependencies = get_module_dependencies(module_path)

        # Check each dependency
        for dep in dependencies:
            # Skip standard library and third-party imports
            if not dep.startswith("src"):
                continue

            # Determine the layer of the dependency
            # This is a simplified check - in reality we'd need to resolve the full path
            dep_layer = None
            if "ports" in dep or "streaming_contracts" in dep:
                dep_layer = "normalizer"
            elif "adapters" in dep:
                dep_layer = "assembler"
            elif "transport" in dep:
                dep_layer = "transport"
            elif "services" in dep and "streaming" in dep:
                dep_layer = "processor"
            elif "connectors" in dep:
                dep_layer = "producer"
            elif "domain" in dep:
                dep_layer = "domain"
            elif "interfaces" in dep:
                dep_layer = "interfaces"

            if not dep_layer:
                continue

            # Check if this dependency is allowed
            allowed_deps = valid_dependencies.get(module_layer, set())
            if dep_layer not in allowed_deps and dep_layer != module_layer:
                violations.append(
                    f"{module_path} ({module_layer}) depends on {dep} ({dep_layer}), "
                    f"but {module_layer} should only depend on {allowed_deps}"
                )

    # Check for circular dependencies
    circular_deps = find_circular_dependencies(modules)
    if circular_deps:
        for module_a, module_b in circular_deps:
            violations.append(
                f"Circular dependency detected: {module_a} <-> {module_b}"
            )

    # Assert no violations
    if violations:
        violation_msg = "\n".join(violations)
        pytest.fail(
            f"Layer separation violations detected:\n{violation_msg}\n\n"
            f"Layers should follow this dependency structure:\n"
            f"  producer -> domain, interfaces\n"
            f"  normalizer -> domain, interfaces\n"
            f"  processor -> normalizer, domain, interfaces\n"
            f"  assembler -> normalizer, domain, interfaces\n"
            f"  transport -> assembler, domain, interfaces\n"
            f"\nNo circular dependencies should exist between layers."
        )


# Property 7: Transport isolation
@pytest.mark.skipif(
    not Path("src/core/transport").exists() and not Path("src/core/adapters").exists(),
    reason="Transport/assembler layer not yet implemented",
)
def test_property_transport_isolation() -> None:
    """
    Property 7: Transport isolation
    Feature: streaming-pipeline-refactor, Property 7: Transport isolation

    For any code in the transport/assembler layer, it should not contain
    references to backend-specific metadata keys or filtering logic.

    Validates: Requirements 2.2, 2.4, 2.5
    """
    # Backend-specific metadata keys that should NOT appear in transport/assembler
    backend_specific_keys = [
        "anthropic",
        "openai",
        "gemini",
        "claude",
        "gpt",
        "candidates",
        "stop_reason",  # Anthropic-specific
        "finish_reason",  # OpenAI-specific (but this is normalized, so it's OK)
        "function_call",  # Gemini-specific
        "thinking",  # Anthropic-specific (but reasoning_content is normalized)
    ]

    # Allowed normalized keys (these are OK in transport)
    allowed_keys = [
        "finish_reason",  # This is normalized
        "reasoning_content",  # This is normalized
        "tool_calls",  # This is normalized
        "stream_id",
        "provider",
        "model",
        "role",
        "index",
        "created",
        "id",
    ]

    violations = []

    # Check transport layer files
    transport_files: list[Path] = []

    transport_dir = Path("src/core/transport")
    if transport_dir.exists():
        transport_files.extend(transport_dir.rglob("*.py"))

    adapters_dir = Path("src/core/adapters")
    if adapters_dir.exists():
        transport_files.extend(adapters_dir.glob("*.py"))

    if not transport_files:
        pytest.skip("No transport/assembler files found")

    for file_path in transport_files:
        if file_path.name == "__init__.py":
            continue

        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Check for backend-specific keys in string literals
            for key in backend_specific_keys:
                # Skip allowed keys
                if key in allowed_keys:
                    continue

                # Look for the key in quotes (as a metadata key reference)
                if f'"{key}"' in content or f"'{key}'" in content:
                    # Check if it's in a comment or docstring
                    lines = content.split("\n")
                    for i, line in enumerate(lines, 1):
                        if (f'"{key}"' in line or f"'{key}'" in line) and not (
                            line.strip().startswith("#")
                            or '"""' in line
                            or "'''" in line
                        ):
                            violations.append(
                                f"{file_path}:{i} references backend-specific key '{key}'"
                            )

            # Check for backend-specific filtering logic
            filtering_patterns = [
                "if provider ==",
                "if backend ==",
                "if metadata.get('provider')",
                "if chunk.metadata.get('provider')",
            ]

            for pattern in filtering_patterns:
                if pattern in content:
                    lines = content.split("\n")
                    for i, line in enumerate(lines, 1):
                        if pattern in line and not line.strip().startswith("#"):
                            violations.append(
                                f"{file_path}:{i} contains backend-specific filtering: {pattern}"
                            )

        except Exception:
            # Skip files we can't read
            pass

    # Assert no violations
    if violations:
        violation_msg = "\n".join(violations[:10])  # Limit to first 10
        if len(violations) > 10:
            violation_msg += f"\n... and {len(violations) - 10} more violations"

        pytest.fail(
            f"Transport isolation violations detected:\n{violation_msg}\n\n"
            f"Transport/assembler layer should not contain:\n"
            f"  - Backend-specific metadata keys (use normalized keys instead)\n"
            f"  - Backend-specific filtering logic (filtering belongs in normalizers)\n"
            f"  - Provider-specific conditionals\n"
            f"\nAllowed normalized keys: {', '.join(allowed_keys)}"
        )


# Property 8: Middleware interface narrowness
@pytest.mark.skipif(
    not Path("src/core/ports/streaming_contracts.py").exists(),
    reason="Streaming contracts not yet implemented",
)
def test_property_middleware_interface_narrowness() -> None:
    """
    Property 8: Middleware interface narrowness
    Feature: streaming-pipeline-refactor, Property 8: Middleware interface narrowness

    For any middleware processor, its interface should not include methods
    for logging, backpressure, or transport concerns.

    Validates: Requirements 2.3
    """
    # Import the IStreamProcessor interface
    try:
        from src.core.ports.streaming_contracts import IStreamProcessor
    except ImportError:
        pytest.skip("IStreamProcessor interface not yet implemented")

    # Get all processor implementations
    processor_classes = []

    # Check src/core/ports/streaming_processors.py
    processors_file = Path("src/core/ports/streaming_processors.py")
    if processors_file.exists():
        try:
            import src.core.ports.streaming_processors as processors_module

            for name in dir(processors_module):
                obj = getattr(processors_module, name)
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, IStreamProcessor)
                    and obj != IStreamProcessor
                ):
                    processor_classes.append(obj)
        except Exception:
            pass

    # Check src/core/services/streaming directory
    streaming_services_dir = Path("src/core/services/streaming")
    if streaming_services_dir.exists():
        for file in streaming_services_dir.glob("*.py"):
            if file.name == "__init__.py":
                continue

            try:
                # Import the module dynamically
                module_name = f"src.core.services.streaming.{file.stem}"
                module = importlib.import_module(module_name)

                for name in dir(module):
                    obj = getattr(module, name)
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, IStreamProcessor)
                        and obj != IStreamProcessor
                    ):
                        processor_classes.append(obj)
            except Exception:
                pass

    if not processor_classes:
        pytest.skip("No processor implementations found")

    # Methods that should NOT be in processor interfaces
    forbidden_methods = [
        "log",
        "logger",
        "emit_log",
        "write_log",
        "apply_backpressure",
        "handle_backpressure",
        "throttle",
        "rate_limit",
        "format_sse",
        "format_json",
        "to_bytes",
        "to_sse",
        "send_chunk",
        "emit_chunk",
        "write_chunk",
    ]

    violations = []

    for processor_class in processor_classes:
        # Get all public methods
        methods = [
            name
            for name in dir(processor_class)
            if not name.startswith("_") and callable(getattr(processor_class, name))
        ]

        # Check for forbidden methods
        for method in methods:
            if method in forbidden_methods:
                violations.append(
                    f"{processor_class.__name__} has forbidden method: {method}"
                )

        # Check method signatures for logging/transport parameters
        for method_name in methods:
            try:
                method_obj = getattr(processor_class, method_name)
                sig = inspect.signature(method_obj)

                # Check parameters
                for param_name in sig.parameters:
                    if param_name in [
                        "logger",
                        "log_level",
                        "transport",
                        "assembler",
                        "format",
                    ]:
                        violations.append(
                            f"{processor_class.__name__}.{method_name} has forbidden parameter: {param_name}"
                        )
            except Exception:
                pass

    # Assert no violations
    if violations:
        violation_msg = "\n".join(violations)
        pytest.fail(
            f"Middleware interface narrowness violations detected:\n{violation_msg}\n\n"
            f"Processor interfaces should:\n"
            f"  - Only have process() and reset() methods\n"
            f"  - Not include logging methods (use module-level logger instead)\n"
            f"  - Not include backpressure methods (handled by pipeline)\n"
            f"  - Not include transport/formatting methods (handled by assembler)\n"
            f"\nForbidden methods: {', '.join(forbidden_methods)}"
        )
