"""demo_real_batch.py – proves gemini-cli-batch backend works with real CLI.
Requires:
  • gemini CLI installed and on PATH
  • GOOGLE_CLOUD_PROJECT env var set (Vertex AI mode)
"""

import json
import os
import pathlib
import sys
import tempfile

from fastapi.testclient import TestClient

# Ensure repo root on path
root = pathlib.Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from src.core.app.application_builder import build_app

# Guarantee GOOGLE_CLOUD_PROJECT is set (fallback demo value)
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "project1-465615")

project_dir = tempfile.mkdtemp(prefix="gemini_batch_real_")
print("Project dir:", project_dir)

app = build_app(
    {
        "backend": "gemini-cli-batch",
        "disable_auth": True,
        "disable_accounting": True,
    }
)

with TestClient(app) as client:
    # 1️⃣ set project dir
    r1 = client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": f'!/set(project-dir="{project_dir}")'}
            ],
        },
    )
    print("Set-cmd:", r1.json()["choices"][0]["message"]["content"])

    # 2️⃣ send prompt
    r2 = client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini-2.5-flash",
            "messages": [{"role": "user", "content": "Tell me a one-line joke"}],
        },
    )
    print(json.dumps(r2.json()["choices"][0], indent=2))
