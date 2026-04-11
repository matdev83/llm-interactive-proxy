from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.config.app_config import AppConfig


def test_app_config_accepts_usage_window_warmup_entries() -> None:
    config = AppConfig.model_validate(
        {
            "usage_window_warmup": {
                "enabled": True,
                "entries": [
                    {
                        "model": "openai-codex:gpt-5.4-mini",
                        "time": "08:00",
                        "execute_on_weekend": True,
                    },
                    {
                        "model": "gemini.2:google/gemini-2.5-flash",
                        "time": "18:45",
                    },
                ],
            }
        }
    )

    warmup = config.usage_window_warmup
    assert warmup.enabled is True
    assert len(warmup.entries) == 2
    assert warmup.entries[0].model == "openai-codex:gpt-5.4-mini"
    assert warmup.entries[0].time == "08:00"
    assert warmup.entries[0].execute_on_weekend is True
    assert warmup.entries[1].model == "gemini.2:google/gemini-2.5-flash"
    assert warmup.entries[1].time == "18:45"
    assert warmup.entries[1].execute_on_weekend is False


def test_app_config_defaults_usage_window_warmup_weekend_execution_to_false() -> None:
    config = AppConfig.model_validate(
        {
            "usage_window_warmup": {
                "enabled": True,
                "entries": [
                    {
                        "model": "openai-codex:gpt-5.4-mini",
                        "time": "08:00",
                    }
                ],
            }
        }
    )

    assert config.usage_window_warmup.entries[0].execute_on_weekend is False


@pytest.mark.parametrize(
    ("model", "expected_message"),
    [
        ("alias:smart", "explicit backend:model route"),
        ("gpt-5.4-mini", "explicit backend:model route"),
        ("openai^anthropic:gpt-5.4-mini", "composite routing operators"),
        ("openai|anthropic:gpt-5.4-mini", "composite routing operators"),
        ("openai:", "non-empty backend and model"),
    ],
)
def test_app_config_rejects_invalid_usage_window_warmup_models(
    model: str, expected_message: str
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        AppConfig.model_validate(
            {
                "usage_window_warmup": {
                    "enabled": True,
                    "entries": [{"model": model, "time": "08:00"}],
                }
            }
        )


@pytest.mark.parametrize("time_value", ["8:00", "24:00", "12:60", "hello"])
def test_app_config_rejects_invalid_usage_window_warmup_times(
    time_value: str,
) -> None:
    with pytest.raises(ValidationError, match="HH:MM"):
        AppConfig.model_validate(
            {
                "usage_window_warmup": {
                    "enabled": True,
                    "entries": [
                        {
                            "model": "openai-codex:gpt-5.4-mini",
                            "time": time_value,
                        }
                    ],
                }
            }
        )
