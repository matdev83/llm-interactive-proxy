from src.connectors.gemini_base.token_estimator import TiktokenEstimator


class _LenEncoding:
    """Deterministic test encoding: one token per character."""

    def encode(self, text: str) -> list[int]:
        return list(range(len(text)))


def test_estimate_prompt_tokens_includes_structured_parts() -> None:
    estimator = TiktokenEstimator(encoding=_LenEncoding())

    base_request = {
        "systemInstruction": {"parts": [{"text": "system"}]},
        "contents": [{"parts": [{"text": "hello"}]}],
    }
    structured_request = {
        "systemInstruction": {"parts": [{"text": "system"}]},
        "contents": [
            {
                "parts": [
                    {
                        "functionResponse": {
                            "name": "tool_x",
                            "response": {"result": "x" * 5000},
                        }
                    }
                ]
            },
            {"parts": [{"text": "hello"}]},
        ],
    }

    base_tokens = estimator.estimate_prompt_tokens(base_request)
    structured_tokens = estimator.estimate_prompt_tokens(structured_request)

    assert isinstance(base_tokens, int)
    assert isinstance(structured_tokens, int)
    assert structured_tokens > base_tokens + 1000
