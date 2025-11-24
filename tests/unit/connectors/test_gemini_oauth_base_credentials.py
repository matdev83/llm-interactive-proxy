from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector


def test_credentials_fingerprint_changes_with_token() -> None:
    base_payload = {
        "access_token": "token-a",
        "refresh_token": "refresh-1",
        "expiry_date": 123,
    }
    fp_a = GeminiOAuthBaseConnector._compute_credentials_fingerprint(base_payload)

    updated_payload = dict(base_payload)
    updated_payload["access_token"] = "token-b"
    fp_b = GeminiOAuthBaseConnector._compute_credentials_fingerprint(updated_payload)

    assert fp_a != fp_b


def test_credentials_fingerprint_same_for_equivalent_payloads() -> None:
    payload_one = {
        "access_token": "token-a",
        "refresh_token": "refresh-1",
        "expiry_date": 123,
    }
    payload_two = {
        "refresh_token": "refresh-1",
        "expiry_date": 123,
        "access_token": "token-a",
    }

    fp_one = GeminiOAuthBaseConnector._compute_credentials_fingerprint(payload_one)
    fp_two = GeminiOAuthBaseConnector._compute_credentials_fingerprint(payload_two)

    assert fp_one == fp_two
