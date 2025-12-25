from pydantic import BaseModel, ConfigDict, Field


class Tier(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    tier_id: str | None = Field(None, alias="tierId")
    is_default: bool | None = Field(None, alias="isDefault")
    max_context_tokens: int | None = Field(None, alias="maxContextTokens")
    context_token_limit: int | None = Field(None, alias="contextTokenLimit")
    context_window_tokens: int | None = Field(None, alias="contextWindowTokens")
    token_limit: int | None = Field(None, alias="tokenLimit")
    max_context_window: int | None = Field(None, alias="maxContextWindow")

    @property
    def canonical_id(self) -> str:
        raw_id = self.id or self.tier_id or ""
        return str(raw_id).lower()

    @property
    def context_tokens(self) -> int:
        for val in [
            self.max_context_tokens,
            self.context_token_limit,
            self.context_window_tokens,
            self.token_limit,
            self.max_context_window,
        ]:
            if val is not None:
                return int(val)
        return 0

    @property
    def is_paid(self) -> bool:
        return self.canonical_id in {
            "paid-tier",
            "google-one-tier",
            "googleone-tier",
            "googleone",
            "duet-ai-pro",
        }
