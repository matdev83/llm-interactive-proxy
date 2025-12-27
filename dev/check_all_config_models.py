"""List all config model classes and their fields."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import importlib.util


def inspect_module(module_path: Path, module_name: str):
    """Inspect a Python module for DomainModel classes."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        return []
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    classes = []
    for name in dir(module):
        obj = getattr(module, name)
        if hasattr(obj, '__bases__'):
            try:
                from src.core.interfaces.model_bases import DomainModel
                if issubclass(obj, DomainModel) and obj != DomainModel:
                    if hasattr(obj, 'model_fields'):
                        classes.append((name, obj))
            except (ImportError, TypeError):
                pass
    
    return classes

models_dir = Path('src/core/config/models')
all_classes = []

for model_file in models_dir.glob('*.py'):
    if model_file.name.startswith('_'):
        continue
    
    module_name = f"src.core.config.models.{model_file.stem}"
    classes = inspect_module(model_file, module_name)
    for cls_name, cls in classes:
        all_classes.append((module_name, cls_name, set(cls.model_fields.keys())))

print(f"Found {len(all_classes)} config model classes:\n")

for module, name, fields in sorted(all_classes):
    print(f"{module}.{name}")
    print(f"  Fields: {sorted(fields)}\n")
