"""Constants for OpenAI Codex managed OAuth flows."""

from __future__ import annotations

DEFAULT_STORAGE_PATH = "var/openai_codex_oauth_accounts"
DEFAULT_SELECTION_STRATEGY = "round-robin"
DEFAULT_REFRESH_BUFFER_SECONDS = 300
DEFAULT_SESSION_AFFINITY_TTL_SECONDS = 86400
DEFAULT_SESSION_AFFINITY_MAX_ENTRIES = 10000
DEFAULT_ALLOW_LEGACY_FALLBACK = True

OPENAI_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_OAUTH_SCOPES: tuple[str, ...] = ("openid", "profile", "email", "offline_access")

