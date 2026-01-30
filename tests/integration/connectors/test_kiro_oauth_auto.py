"""
Integration tests for Kiro OAuth Auto-Connector.
"""

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from src.connectors.kiro_oauth_auto.connector import KiroOAuthAutoConnector
from src.connectors.kiro_oauth_auto.constants import CODEWHISPERER_LIST_MODELS_URL
from src.connectors.kiro_oauth_auto.models import StoredAccount
from src.connectors.kiro_oauth_auto.token_storage import TokenStorageService
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService
from tests.unit.fixtures.markers import real_time


@pytest.mark.integration
@real_time(
    reason="Integration tests use real time for async task scheduling and coordination"
)
class TestKiroOAuthAutoIntegration:
    """Integration tests for Kiro OAuth Auto-Connector services."""

    @pytest.mark.asyncio
    async def test_connector_waits_for_shortest_rate_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Connector waits for the earliest rate-limited account on init."""
        from src.connectors.kiro_oauth_auto import account_selector as module_under_test

        storage_dir = tmp_path / "kiro_oauth_accounts"
        storage_dir.mkdir()

        base_time = 1768780800.0
        base_ms = int(base_time * 1000)

        storage = TokenStorageService(storage_path=storage_dir)
        await storage.save_account(
            StoredAccount(
                account_id="acc-1",
                auth_method="builderid",
                region="us-east-1",
                access_token="access-1",
                refresh_token="refresh-1",
                client_id="client-1",
                client_secret="secret-1",
                expiry_date=base_ms + 3600_000,
                rate_limited_until=base_ms + 5000,
            )
        )
        await storage.save_account(
            StoredAccount(
                account_id="acc-2",
                auth_method="builderid",
                region="us-east-1",
                access_token="access-2",
                refresh_token="refresh-2",
                client_id="client-2",
                client_secret="secret-2",
                expiry_date=base_ms + 3600_000,
                rate_limited_until=base_ms + 12_000,
            )
        )

        sleep_mock = AsyncMock()
        monkeypatch.setattr(module_under_test.asyncio, "sleep", sleep_mock)

        times = iter([base_time, base_time + 5.1])

        def fake_time() -> float:
            return next(times, base_time + 5.1)

        monkeypatch.setattr(module_under_test.time, "time", fake_time)

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == CODEWHISPERER_LIST_MODELS_URL:
                return httpx.Response(200, json={"models": []})
            return httpx.Response(404, json={"error": "not found"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        config = AppConfig(
            {
                "backends": {
                    "kiro-oauth-auto": {
                        "type": "kiro-oauth-auto",
                        "extra": {"storage_path": str(storage_dir)},
                    }
                }
            }
        )
        connector = KiroOAuthAutoConnector(
            client=client,
            config=config,
            translation_service=TranslationService(),
        )

        await connector.initialize()

        current = connector._selector.get_current_account()
        assert current is not None
        assert current.account_id == "acc-1"
        assert sleep_mock.await_count == 1
        assert sleep_mock.await_args is not None
        assert sleep_mock.await_args.args[0] == pytest.approx(5.0)

        await client.aclose()
