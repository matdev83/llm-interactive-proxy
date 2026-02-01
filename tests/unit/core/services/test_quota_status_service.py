from src.core.services.quota_status_service import QuotaStatusService


class TestQuotaStatusService:
    def test_update_and_get_quota(self):
        service = QuotaStatusService()
        headers = {
            "x-codex-primary-used-percent": "50.0",
            "x-ratelimit-limit-requests": "1000",
            "content-type": "application/json"  # Should be ignored
        }
        
        service.update_quota("openai", headers)
        
        captured = service.get_quota_headers("openai")
        assert captured["x-codex-primary-used-percent"] == "50.0"
        assert captured["x-ratelimit-limit-requests"] == "1000"
        assert "content-type" not in captured

    def test_get_merged_quota_headers(self):
        service = QuotaStatusService()
        service.update_quota("openai", {"x-codex-primary-used-percent": "50.0"})
        service.update_quota("anthropic", {"x-usage-custom": "val"})
        
        merged = service.get_quota_headers()
        assert merged["x-codex-primary-used-percent"] == "50.0"
        assert merged["x-usage-custom"] == "val"

    def test_get_all_quotas(self):
        service = QuotaStatusService()
        service.update_quota("openai", {"x-codex-primary-used-percent": "50.0"})
        
        all_quotas = service.get_all_quotas()
        assert "openai" in all_quotas
        assert all_quotas["openai"]["x-codex-primary-used-percent"] == "50.0"
