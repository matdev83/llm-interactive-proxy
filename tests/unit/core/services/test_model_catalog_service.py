import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from src.core.config.models.misc import ModelRegistryConfig
from src.core.domain.model_catalog_match import ModelCatalogMatchTier
from src.core.services.model_catalog_service import ModelCatalogService


def _service_from_data(mock_data: dict) -> tuple[ModelCatalogService, str]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(mock_data, f)
        temp_path = f.name
    config = ModelRegistryConfig(bootstrap_path=temp_path, cache_path=temp_path)
    return ModelCatalogService(config), temp_path


def test_model_catalog_parsing() -> None:
    mock_data = {
        "provider1": {
            "models": {
                "model1": {
                    "limit": {"context": 1000, "output": 100},
                    "modalities": {"input": ["text"], "output": ["text"]},
                }
            }
        },
        "openai": {
            "models": {
                "gpt-4": {
                    "limit": {"context": 8192, "output": 4096},
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                }
            }
        },
    }

    service, temp_path = _service_from_data(mock_data)

    limits = service.get_limits("model1")
    assert limits is not None
    assert limits.context_window == 1000
    assert limits.max_output_tokens == 100

    limits = service.get_limits("gpt-4", "openai")
    assert limits is not None
    assert limits.context_window == 8192

    assert service.get_limits("provider1:model1") is not None
    assert service.get_limits("openai/gpt-4") is not None

    assert service.get_input_modalities("model1") == {"text"}
    assert service.get_input_modalities("gpt-4", "openai") == {"text", "image"}

    assert service.has_model("model1") is True
    assert service.has_model("gpt-4", "openai") is True
    assert service.has_model("missing-model") is False

    Path(temp_path).unlink()


def test_model_catalog_prefix_matching() -> None:
    mock_data = {
        "anthropic": {
            "models": {
                "claude-3-5-sonnet-20241022": {
                    "limit": {"context": 200000, "output": 8192}
                }
            }
        }
    }

    service, temp_path = _service_from_data(mock_data)

    limits = service.get_limits("claude-3-5-sonnet", "anthropic")
    assert limits is not None
    assert limits.context_window == 200000

    assert service.has_model("claude-3-5-sonnet", "anthropic") is True

    Path(temp_path).unlink()


def test_ambiguous_bare_id_unscoped_returns_none() -> None:
    """Same model id string under two providers: unscoped lookup must abstain."""
    mock_data = {
        "openai": {
            "models": {
                "shared-id": {
                    "limit": {"context": 100, "output": 10},
                }
            }
        },
        "anthropic": {
            "models": {
                "shared-id": {
                    "limit": {"context": 200, "output": 20},
                }
            }
        },
    }
    service, temp_path = _service_from_data(mock_data)
    assert service.get_limits("shared-id") is None
    r = service.resolve("shared-id", None)
    assert r.tier == ModelCatalogMatchTier.NONE
    assert r.limits is None

    r_openai = service.resolve("shared-id", "openai")
    assert r_openai.limits is not None
    assert r_openai.limits.context_window == 100
    r_anth = service.resolve("shared-id", "anthropic")
    assert r_anth.limits is not None
    assert r_anth.limits.context_window == 200

    Path(temp_path).unlink()


def test_casefold_normalized_match() -> None:
    mock_data = {
        "openai": {
            "models": {
                "GPT-4o": {
                    "limit": {"context": 128000, "output": 16384},
                }
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    lim = service.get_limits("gpt-4o", "openai")
    assert lim is not None
    assert lim.context_window == 128000
    Path(temp_path).unlink()


def test_strip_free_suffix() -> None:
    mock_data = {
        "openrouter": {
            "models": {
                "meta-llama/llama-3-8b": {
                    "limit": {"context": 8192, "output": 4096},
                }
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    lim = service.get_limits("meta-llama/llama-3-8b:free", "openrouter")
    assert lim is not None
    assert lim.context_window == 8192
    Path(temp_path).unlink()


def test_prefix_too_short_abstains() -> None:
    mock_data = {
        "openai": {
            "models": {
                "gpt-4": {"limit": {"context": 100, "output": 10}},
                "gpt-5": {"limit": {"context": 200, "output": 20}},
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    assert service.get_limits("gpt", "openai") is None
    Path(temp_path).unlink()


def test_vendor_tail_unique_unscoped() -> None:
    mock_data = {
        "p-a": {"models": {"only-here": {"limit": {"context": 1, "output": 1}}}},
        "p-b": {"models": {"other": {"limit": {"context": 2, "output": 2}}}},
    }
    service, temp_path = _service_from_data(mock_data)
    lim = service.get_limits("only-here")
    assert lim is not None
    assert lim.context_window == 1
    Path(temp_path).unlink()


def test_vendor_tail_ambiguous_unscoped_abstains() -> None:
    mock_data = {
        "openai": {"models": {"gpt-4": {"limit": {"context": 100, "output": 10}}}},
        "anthropic": {"models": {"gpt-4": {"limit": {"context": 200, "output": 20}}}},
    }
    service, temp_path = _service_from_data(mock_data)
    assert service.get_limits("gpt-4") is None
    Path(temp_path).unlink()


def test_resolve_records_tier_and_key() -> None:
    mock_data = {
        "anthropic": {
            "models": {
                "claude-3-5-sonnet-20241022": {
                    "limit": {"context": 200000, "output": 8192},
                    "modalities": {"input": ["text"], "output": ["text"]},
                }
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    r = service.resolve("claude-3-5-sonnet", "anthropic")
    assert r.tier == ModelCatalogMatchTier.PREFIX
    assert r.resolved_catalog_key == "anthropic/claude-3-5-sonnet-20241022"
    assert r.catalog_provider_id == "anthropic"
    assert r.limits is not None
    Path(temp_path).unlink()


def test_gemini_backend_maps_to_google_provider() -> None:
    mock_data = {
        "google": {
            "models": {
                "gemini-2.0-flash": {
                    "limit": {"context": 1000000, "output": 8192},
                }
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    lim = service.get_limits("gemini-2.0-flash", "gemini")
    assert lim is not None
    assert lim.context_window == 1000000
    Path(temp_path).unlink()


def test_openai_codex_backend_maps_to_openai() -> None:
    mock_data = {
        "openai": {
            "models": {
                "gpt-4.1": {"limit": {"context": 1000000, "output": 32768}},
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    lim = service.get_limits("gpt-4.1", "openai-codex")
    assert lim is not None
    assert lim.context_window == 1000000
    Path(temp_path).unlink()


def test_catalog_not_loaded_when_bootstrap_file_missing() -> None:
    missing = str(Path(tempfile.mkdtemp()) / "nonexistent-models.dev.json")
    alt = str(Path(tempfile.mkdtemp()) / "cache-missing-too.json")
    config = ModelRegistryConfig(bootstrap_path=missing, cache_path=alt)
    service = ModelCatalogService(config)
    r = service.resolve("gpt-4", "openai")
    assert r.tier == ModelCatalogMatchTier.NONE
    assert service.has_model("anything") is False
    assert service.get_limits("x") is None


def test_catalog_not_loaded_empty_json_object() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("{}")
        temp_path = f.name
    config = ModelRegistryConfig(bootstrap_path=temp_path, cache_path=temp_path)
    service = ModelCatalogService(config)
    assert service.resolve("a", None).tier == ModelCatalogMatchTier.NONE
    Path(temp_path).unlink()


def test_resolve_exact_tier_documented() -> None:
    mock_data = {
        "openai": {
            "models": {
                "gpt-4": {"limit": {"context": 8192, "output": 4096}},
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    r = service.resolve("gpt-4", "openai")
    assert r.tier == ModelCatalogMatchTier.EXACT
    assert r.resolved_catalog_key == "openai/gpt-4"
    Path(temp_path).unlink()


def test_resolve_normalized_tier_documented() -> None:
    mock_data = {
        "openai": {"models": {"MiXeD-CaSe-Id": {"limit": {"context": 1, "output": 1}}}}
    }
    service, temp_path = _service_from_data(mock_data)
    r = service.resolve("mixed-case-id", "openai")
    assert r.tier == ModelCatalogMatchTier.NORMALIZED
    Path(temp_path).unlink()


def test_strip_nitro_suffix_variant() -> None:
    mock_data = {
        "openrouter": {
            "models": {
                "x/y": {"limit": {"context": 5000, "output": 1000}},
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    lim = service.get_limits("x/y:nitro", "openrouter")
    assert lim is not None
    assert lim.context_window == 5000
    Path(temp_path).unlink()


def test_unknown_backend_unscoped_resolves_unique_model() -> None:
    """Unmapped backend falls back to unscoped resolution."""
    mock_data = {
        "openai": {
            "models": {"solo-model-xyz": {"limit": {"context": 99, "output": 9}}}
        }
    }
    service, temp_path = _service_from_data(mock_data)
    r = service.resolve("solo-model-xyz", "custom-proxy-backend")
    assert r.limits is not None
    assert r.limits.context_window == 99
    assert r.tier == ModelCatalogMatchTier.NORMALIZED
    Path(temp_path).unlink()


def test_unknown_backend_ambiguous_returns_none() -> None:
    mock_data = {
        "openai": {"models": {"dup": {"limit": {"context": 1, "output": 1}}}},
        "anthropic": {"models": {"dup": {"limit": {"context": 2, "output": 2}}}},
    }
    service, temp_path = _service_from_data(mock_data)
    assert service.resolve("dup", "unknown-backend").tier == ModelCatalogMatchTier.NONE
    Path(temp_path).unlink()


def test_typo_near_catalog_id_uses_token_overlap_before_fuzzy() -> None:
    """Near-miss (not a prefix) is handled by TOKEN_OVERLAP before difflib FUZZY."""
    mock_data = {
        "anthropic": {
            "models": {
                "claude-3-sonnet-20240229": {
                    "limit": {"context": 200000, "output": 4096},
                }
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    r = service.resolve("claude-3-sonnet-20240228", "anthropic")
    assert r.tier == ModelCatalogMatchTier.TOKEN_OVERLAP
    assert r.limits is not None
    assert r.limits.context_window == 200000
    Path(temp_path).unlink()


def test_fuzzy_tier_when_token_overlap_returns_none() -> None:
    mock_data = {
        "anthropic": {
            "models": {
                "claude-3-sonnet-20240229": {
                    "limit": {"context": 200000, "output": 4096},
                }
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    with patch.object(
        ModelCatalogService,
        "_token_overlap_pick",
        return_value=None,
    ):
        r = service.resolve("claude-3-sonnet-20240228", "anthropic")
    assert r.tier == ModelCatalogMatchTier.FUZZY
    assert r.limits.context_window == 200000
    Path(temp_path).unlink()


def test_token_overlap_tier_when_prefix_does_not_apply() -> None:
    """Request token set overlaps one catalog id without being a prefix of it."""
    mock_data = {
        "openai": {
            "models": {
                "my-story-teller-mega-model": {
                    "limit": {"context": 50000, "output": 8000},
                }
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    r = service.resolve("story-teller-mega", "openai")
    assert r.tier == ModelCatalogMatchTier.TOKEN_OVERLAP
    assert r.limits.context_window == 50000
    Path(temp_path).unlink()


def test_prefix_ambiguous_two_extensions_abstains_prefix_then_fuzzy_may_fail() -> None:
    """Two catalog ids share the same long prefix stem: PREFIX tier must not pick one."""
    mock_data = {
        "anthropic": {
            "models": {
                "claude-longstem-aaaa": {"limit": {"context": 100, "output": 10}},
                "claude-longstem-bbbb": {"limit": {"context": 200, "output": 20}},
            }
        }
    }
    service, temp_path = _service_from_data(mock_data)
    r = service.resolve("claude-longstem", "anthropic")
    assert len("claude-longstem") >= 8
    assert r.tier != ModelCatalogMatchTier.PREFIX
    Path(temp_path).unlink()


def test_unscoped_slash_path_resolves_by_tail() -> None:
    mock_data = {
        "openai": {
            "models": {"group/submodel": {"limit": {"context": 42, "output": 7}}}
        }
    }
    service, temp_path = _service_from_data(mock_data)
    r = service.resolve("openai/group/submodel", None)
    assert r.limits is not None
    assert r.limits.context_window == 42
    Path(temp_path).unlink()


def test_parse_skips_non_dict_models_block() -> None:
    mock_data = {
        "bad": "not-a-dict",
        "openai": {"models": {"ok": {"limit": {"context": 3, "output": 1}}}},
    }
    service, temp_path = _service_from_data(mock_data)
    assert service.get_limits("ok", "openai") is not None
    Path(temp_path).unlink()


def test_modalities_absent_returns_none_input_modalities() -> None:
    mock_data = {
        "openai": {"models": {"no-mods": {"limit": {"context": 100, "output": 10}}}}
    }
    service, temp_path = _service_from_data(mock_data)
    r = service.resolve("no-mods", "openai")
    assert r.limits is not None
    assert r.input_modalities is None
    assert service.get_input_modalities("no-mods", "openai") is None
    Path(temp_path).unlink()


@pytest.mark.parametrize(
    ("backend", "expected_provider"),
    [
        ("gemini-oauth-free", "google"),
        ("antigravity-oauth", "google"),
        ("kiro-oauth-auto", "google"),
    ],
)
def test_backend_alias_maps_to_google(backend: str, expected_provider: str) -> None:
    mock_data = {
        expected_provider: {"models": {"p": {"limit": {"context": 1, "output": 1}}}}
    }
    service, temp_path = _service_from_data(mock_data)
    assert service.get_limits("p", backend) is not None
    Path(temp_path).unlink()
