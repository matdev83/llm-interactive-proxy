import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.backend_config_service import BackendConfigService


def test_gemini_generation_config_receives_temperature_override() -> None:
    # Given a ChatRequest with a lowered temperature from edit-precision
    req = ChatRequest(
        model="gemini-1.5-pro",
        messages=[
            ChatMessage(
                role="user",
                content="The SEARCH block ... does not match anything in the file",
            )
        ],
        temperature=0.05,
        top_p=0.2,
    )

    cfg = AppConfig()
    svc = BackendConfigService()

    # When applying backend-specific config for Gemini
    out = svc.apply_backend_config(req, backend_type="gemini", config=cfg)

    # Then the gemini_generation_config should reflect the per-call temperature override
    assert out.extra_body is not None
    gen = out.extra_body.get("gemini_generation_config")
    assert isinstance(gen, dict)
    assert gen.get("temperature") == pytest.approx(0.05)
