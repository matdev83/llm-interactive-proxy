from pathlib import Path
import tomli

def _load_project_metadata() -> tuple[str, str]:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml" # Changed parents[1] to parents[2]
    try:
        data = tomli.loads(pyproject.read_text())
        meta = data.get("project", {})
        return meta.get("name", "llm-interactive-proxy"), meta.get("version", "0.0.0")
    except Exception:
        return "llm-interactive-proxy", "0.0.0"
