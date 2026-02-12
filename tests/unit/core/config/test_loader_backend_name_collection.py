from __future__ import annotations

from src.core.config.loading.loader import _collect_backend_instance_names


def test_collect_backend_names_includes_non_dotted_entries() -> None:
    names = _collect_backend_instance_names(
        {
            "backends": {
                "default_backend": "openai",
                "openai": {"timeout": 120},
                "openai.1": {"connector": "openai"},
                "gemini_oauth_auto": {"timeout": 120},
            }
        }
    )

    assert "default_backend" not in names
    assert "openai" in names
    assert "openai.1" in names
    assert "gemini_oauth_auto" in names
