from src.core.services.quota_status_service import (
    QuotaStatusService,
    _format_quota_headers_for_log,
)


class TestFormatQuotaHeadersForLog:
    def test_sorts_and_joins_key_value_pairs(self) -> None:
        formatted = _format_quota_headers_for_log(
            {"z-last": "2", "a-first": "1"},
        )
        assert formatted == "a-first=1, z-last=2"

    def test_collapses_newlines_and_truncates_long_values(self) -> None:
        long_val = "x" * 300
        formatted = _format_quota_headers_for_log(
            {"h": f"line1\nline2\n{long_val}"},
            value_max_len=20,
        )
        assert "line1 line2" in formatted
        assert formatted.endswith("...")


class TestQuotaStatusService:
    def test_update_and_get_quota(self):
        service = QuotaStatusService()
        headers = {
            "x-codex-primary-used-percent": "50.0",
            "x-ratelimit-limit-requests": "1000",
            "content-type": "application/json",  # Should be ignored
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
