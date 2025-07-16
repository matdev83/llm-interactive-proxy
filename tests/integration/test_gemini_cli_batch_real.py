import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

from src.main import build_app


@pytest.mark.integration
def test_gemini_cli_batch_real_roundtrip():
    """Full end-to-end check that the gemini-cli-batch backend can execute a real
    `gemini` process and return a non-empty answer.

    The test **intentionally uses no mocks** – it will fail if either the CLI
    executable is missing or the CLI exits with an error that the proxy
    propagates.  This guards against regressions where the backend silently
    stops working while the unit suite continues to pass.
    """

    # Fail fast if the gemini executable is not on PATH – this should never be
    # the case in the CI environment configured for this project.  We use
    # fail() rather than skip() so that the breakage is caught immediately.
    if shutil.which("gemini") is None:
        pytest.fail("gemini CLI executable not found on PATH – backend real-run test cannot proceed.")

    # Require Vertex-AI env vars; fail loudly if they are missing.
    for var in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"):
        if not os.getenv(var):
            pytest.fail(f"Environment variable {var} must be set for real gemini-cli test.")

    project_dir = tempfile.mkdtemp(prefix="gemini_batch_test_")

    app = build_app({
        "backend": "gemini-cli-batch",
        "disable_auth": True,
        "disable_accounting": True,
    })

    with TestClient(app) as client:
        # Step 1 – configure working directory
        set_payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {
                    "role": "user",
                    "content": f"!/set(project-dir=\"{project_dir}\")",
                }
            ],
        }
        set_resp = client.post("/v1/chat/completions", json=set_payload)
        assert set_resp.status_code == 200, set_resp.text
        assert "project-dir set to" in set_resp.json()["choices"][0]["message"]["content"].lower()

        # Step 2 – normal prompt
        joke_payload = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Tell me a short joke."},
            ],
        }
        resp = client.post("/v1/chat/completions", json=joke_payload)
        assert resp.status_code == 200, resp.text

        result_text = resp.json()["choices"][0]["message"]["content"].strip()

        # The backend must not propagate an error string
        assert "gemini cli failed" not in result_text.lower()
        assert result_text, "gemini-cli returned empty content"

        # Optional sanity: jokes usually contain at least one punctuation mark
        assert any(c in result_text for c in ("?", ".", "!")) 