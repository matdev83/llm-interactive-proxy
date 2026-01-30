from src.core.config.models.misc import ModelRegistryConfig
from src.core.services.model_catalog_service import ModelCatalogService


def test_model_catalog_parsing():
    # Mock data with the observed structure
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

    import json
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(mock_data, f)
        temp_path = f.name

    config = ModelRegistryConfig(bootstrap_path=temp_path, cache_path=temp_path)

    service = ModelCatalogService(config)

    # Test lookups
    limits = service.get_limits("model1")
    assert limits is not None
    assert limits.context_window == 1000
    assert limits.max_output_tokens == 100

    limits = service.get_limits("gpt-4", "openai")
    assert limits is not None
    assert limits.context_window == 8192

    # Test prefixed keys
    assert service.get_limits("provider1:model1") is not None
    assert service.get_limits("openai/gpt-4") is not None

    # Test modality lookups
    assert service.get_input_modalities("model1") == {"text"}
    assert service.get_input_modalities("gpt-4", "openai") == {"text", "image"}

    assert service.has_model("model1") is True
    assert service.has_model("gpt-4", "openai") is True
    assert service.has_model("missing-model") is False

    Path(temp_path).unlink()


def test_model_catalog_prefix_matching():
    mock_data = {
        "anthropic": {
            "models": {
                "claude-3-5-sonnet-20241022": {
                    "limit": {"context": 200000, "output": 8192}
                }
            }
        }
    }

    import json
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(mock_data, f)
        temp_path = f.name

    config = ModelRegistryConfig(bootstrap_path=temp_path, cache_path=temp_path)

    service = ModelCatalogService(config)

    # Prefix match
    limits = service.get_limits("claude-3-5-sonnet", "anthropic")
    assert limits is not None
    assert limits.context_window == 200000

    assert service.has_model("claude-3-5-sonnet", "anthropic") is True

    Path(temp_path).unlink()
