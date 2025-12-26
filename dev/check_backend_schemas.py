"""Check for backend configs that might be missing schema validation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# List all backend config files
backend_dirs = [
    'config/backends/gemini-cli-acp',
    'config/backends/qwen-oauth',
    'config/backends/zai',
    'config/backends/openai_codex'
]

backend_files = []
for d in backend_dirs:
    d_path = Path(d)
    if d_path.exists():
        for f in d_path.glob('*.yaml'):
            backend_files.append(f)

# List all backend schemas
schema_files = list(Path('config/schemas').glob('*backend.schema.yaml'))

print(f"Found {len(backend_files)} backend config files:")
for f in backend_files:
    print(f"  - {f}")

print(f"\nFound {len(schema_files)} backend schema files:")
for f in schema_files:
    print(f"  - {f.name}")

# Check which backend files have corresponding schemas
print("\n\nChecking which backend configs have schemas...")
schema_names = {s.stem.replace('_backend.schema', '') for s in schema_files}

for backend_file in backend_files:
    # Try to infer schema name from backend file name or backend_type
    # For backend files, we need to look at backend_type inside
    import yaml
    try:
        with backend_file.open() as f:
            config = yaml.safe_load(f)
            backend_type = config.get('backend_type', backend_file.stem)
            
            if backend_type in schema_names:
                print(f"  [MATCH] {backend_file.name} -> {backend_type}_backend.schema.yaml")
            else:
                print(f"  [NO MATCH] {backend_file.name} (backend_type={backend_type})")
                print(f"          Available schemas: {sorted(schema_names)}")
    except Exception as e:
        print(f"  [ERROR] {backend_file.name}: {e}")
