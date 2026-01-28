from __future__ import annotations

from src.core.app.controllers.models_controller import (
    _infer_modalities_from_capabilities,
)
from src.core.domain.model_capabilities import KNOWN_MODEL_CAPABILITIES


def test_kimi_model_advertises_text_and_image_modalities() -> None:
    capabilities = KNOWN_MODEL_CAPABILITIES.get("kimi-code:kimi/kimi-for-coding")
    assert capabilities is not None

    input_modalities, output_modalities = _infer_modalities_from_capabilities(
        capabilities
    )
    assert input_modalities == ["text", "image"]
    assert output_modalities == ["text"]
