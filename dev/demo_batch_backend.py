import tempfile, json
import sys, pathlib
from fastapi.testclient import TestClient
from unittest.mock import patch

# Ensure project root is on sys.path when script run directly
project_root = pathlib.Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.main import build_app
from src.connectors.gemini_cli_direct import GeminiCliDirectConnector

# Stub the actual CLI call so we don't need Gemini installed
async def _fake_execute(self, prompt: str, model: str | None = None, sandbox: bool = False):
    return f"FAKE_RESPONSE for prompt: {prompt[:20]} ..."

def run_demo() -> None:
    # 1. Spin up the FastAPI app with gemini-cli-batch as default backend
    app = build_app({
        "backend": "gemini-cli-batch",
        "disable_auth": True,
        "disable_accounting": True,
    })

    project_dir = tempfile.mkdtemp(prefix="gemini_batch_demo_")

    with TestClient(app) as client, patch.object(GeminiCliDirectConnector, "_execute_gemini_cli", new=_fake_execute):
        # Tell the proxy where the local project lives
        set_resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini-2.5-pro",
                "messages": [
                    {"role": "user", "content": f"!/set(project-dir='{project_dir}')"}
                ],
            },
        )
        print("Set command response:", set_resp.json()["choices"][0]["message"]["content"])

        # Now send an arbitrary prompt – it should hit the batch backend and return the stubbed response
        prompt_resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "gemini-2.5-flash",
                "messages": [{"role": "user", "content": "Tell me a joke"}],
            },
        )
        reply = prompt_resp.json()["choices"][0]["message"]["content"]
        print("Backend response:", reply)

        assert reply.startswith("FAKE_RESPONSE"), "Batch backend did not return expected stubbed output"

    print("gemini-cli-batch backend functional ✔")


if __name__ == "__main__":
    run_demo() 