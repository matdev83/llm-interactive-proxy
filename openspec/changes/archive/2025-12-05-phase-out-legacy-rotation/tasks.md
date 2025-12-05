# Tasks: Phase Out Legacy Rotation

- [x] **1. Refactor AppConfig** <!-- id: 1 -->
    - `BackendConfig.api_key` field type changed from `list[str]` to `str | None`.
    - Added backward-compatibility validator that converts legacy list to first string.
    - `_process_api_keys` and `_get_api_keys_from_env` retained for `auth.api_keys` (proxy auth, distinct from backend keys).

- [x] **2. Refactor BackendFactory** <!-- id: 2 -->
    - `backend_factory.py` passes `backend_config.api_key` directly as a string.
    - No `api_key[0]` indexing logic present.

- [x] **3. Refactor Connectors** <!-- id: 3 -->
    - `GeminiBackend`: Uses `self.api_key` (single string), no `self.api_keys` list.
    - `OpenRouterBackend`: Uses `self.api_key` (single string), no `self.api_keys` list.
    - Other connectors (`Anthropic`, `OpenAI`) also use single `api_key`.

- [x] **4. Clean up Legacy Utils** <!-- id: 4 -->
    - `APIKeyRedactor` accepts `Iterable[str]`, handles both single keys and lists gracefully.
    - Discovery functions work with the new single-key per backend structure.

- [x] **5. Update Backend Config Provider** <!-- id: 5 -->
    - `backend_config_provider.py` handles `api_key` as a string via `cfg.api_key` checks.

- [x] **6. Remove Legacy Tests** <!-- id: 6 -->
    - Updated `tests/test_backend_factory.py`: `MockBackendBase.api_keys` changed to `api_key` (single string).
    - Auth-related `api_keys` tests preserved (for proxy authentication, not backend rotation).

- [x] **7. Update Documentation** <!-- id: 7 -->
    - `troubleshooting.md` references multi-instance pattern (`OPENAI_API_KEY_1`, etc.) instead of legacy single-backend key list rotation.
    - Documentation aligned with new multi-instance architecture.

- [x] **8. Verify & Finalize** <!-- id: 8 -->
    - Implementation complete.
    - `BackendSettings` discovery of `OPENAI_API_KEY_1` etc. works via `_discover_backend_instances()`.
    - Multi-instance architecture (`openai.1`, `openai.2`) supersedes legacy key rotation.
