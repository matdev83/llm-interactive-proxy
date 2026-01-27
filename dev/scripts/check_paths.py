import sys
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Mateusz/source/repos/llm-interactive-proxy")
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from src.connectors.gemini_base.credential_providers.sqlite_provider import (
    AntigravitySQLiteCredentialProvider,
)

provider = AntigravitySQLiteCredentialProvider()
print("Searching for candidate paths...")
paths = provider._candidate_state_db_paths()
for p in paths:
    exists = p.exists()
    print(f"Path: {p}, exists: {exists}")
    if exists:
        print(f"Attempting to read from {p}...")
        try:
            val = provider._load_auth_status_from_db(p)
            if val:
                print(f"Successfully read auth status: {list(val.keys())}")
            else:
                print("No auth status found in DB.")
        except Exception as e:
            print(f"Error reading from DB: {e}")
