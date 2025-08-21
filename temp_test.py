import asyncio

from src.core.domain.responses import ResponseEnvelope
from tests.mocks.mock_regression_backend import MockRegressionBackend


async def test_mock():
    backend = MockRegressionBackend()
    result = await backend.chat_completions({}, [], 'test-model')
    if isinstance(result, ResponseEnvelope):
        content = result.content
        
            

asyncio.run(test_mock())
