"""Client-family compatibility adapters for OpenAI Codex connector."""

from src.connectors.openai_codex.client_families.base import (
    FamilyApplyResult,
    IClientFamilyAdapter,
)
from src.connectors.openai_codex.client_families.droid_adapter import (
    DroidClientFamilyAdapter,
)
from src.connectors.openai_codex.client_families.kilo_adapter import (
    KiloClientFamilyAdapter,
)
from src.connectors.openai_codex.client_families.opencode_adapter import (
    OpenCodeClientFamilyAdapter,
)
from src.connectors.openai_codex.client_families.pi_adapter import (
    PiClientFamilyAdapter,
)
from src.connectors.openai_codex.client_families.registry import ClientFamilyRegistry

__all__ = [
    "ClientFamilyRegistry",
    "DroidClientFamilyAdapter",
    "FamilyApplyResult",
    "IClientFamilyAdapter",
    "KiloClientFamilyAdapter",
    "OpenCodeClientFamilyAdapter",
    "PiClientFamilyAdapter",
]
