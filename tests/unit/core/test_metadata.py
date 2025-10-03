import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[3] / "src" / "core" / "metadata.py"
spec = importlib.util.spec_from_file_location("metadata_module", MODULE_PATH)
metadata = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(metadata)


def test_load_project_metadata_reads_pyproject():
    name, version = metadata._load_project_metadata()
    assert name == "llm-interactive-proxy"
    assert version == "0.1.0"


def test_load_project_metadata_handles_read_errors(monkeypatch):
    def raise_error(self, *args, **kwargs):
        raise OSError("unable to read pyproject.toml")

    monkeypatch.setattr(Path, "read_text", raise_error)
    assert metadata._load_project_metadata() == ("llm-interactive-proxy", "0.0.0")
