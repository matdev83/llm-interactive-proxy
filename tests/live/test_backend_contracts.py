import pytest
from anthropic import AsyncAnthropic
from google import genai
from openai import AsyncOpenAI

pytestmark = pytest.mark.live


class TestBackendContracts:
    """
    Verify that the real backend APIs behave as expected.
    These tests hit the actual providers (OpenAI, Anthropic, Gemini).
    """

    @pytest.mark.asyncio
    async def test_openai_contract_simple(self, require_openai: str):
        """Verify basic OpenAI chat completion."""
        client = AsyncOpenAI(api_key=require_openai)

        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Say 'hello'"}],
            max_tokens=10,
        )

        content = response.choices[0].message.content
        assert content is not None
        assert len(content) > 0

    @pytest.mark.asyncio
    async def test_openai_contract_streaming(self, require_openai: str):
        """Verify OpenAI streaming."""
        client = AsyncOpenAI(api_key=require_openai)

        stream = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Count to 3"}],
            stream=True,
            max_tokens=20,
        )

        chunks = []
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)

        full_text = "".join(chunks)
        assert len(full_text) > 0

    @pytest.mark.asyncio
    async def test_anthropic_contract_simple(self, require_anthropic: str):
        """Verify basic Anthropic message creation."""
        client = AsyncAnthropic(api_key=require_anthropic)

        response = await client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say 'hello'"}],
        )

        assert len(response.content) > 0
        assert response.content[0].text is not None

    @pytest.mark.asyncio
    async def test_anthropic_contract_streaming(self, require_anthropic: str):
        """Verify Anthropic streaming."""
        client = AsyncAnthropic(api_key=require_anthropic)

        stream = await client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=20,
            messages=[{"role": "user", "content": "Count to 3"}],
            stream=True,
        )

        chunks = []
        async for event in stream:
            if event.type == "content_block_delta":
                chunks.append(event.delta.text)

        full_text = "".join(chunks)
        assert len(full_text) > 0

    @pytest.mark.asyncio
    async def test_gemini_contract_simple(self, require_gemini: str):
        """Verify basic Gemini content generation."""
        client = genai.Client(api_key=require_gemini)

        # Use client.aio for async operations
        response = await client.aio.models.generate_content(
            model="models/gemini-2.5-flash", contents="Say 'hello'"
        )

        assert response.text is not None
        assert len(response.text) > 0

    @pytest.mark.asyncio
    async def test_gemini_contract_streaming(self, require_gemini: str):
        """Verify Gemini streaming."""
        client = genai.Client(api_key=require_gemini)

        # Streaming in new SDK
        stream = await client.aio.models.generate_content(
            model="models/gemini-2.5-flash",
            contents="Count to 3",
            config={"response_modalities": ["TEXT"]},
        )

        chunks = []
        async for chunk in stream:
            if chunk.text:
                chunks.append(chunk.text)

        full_text = "".join(chunks)
        assert len(full_text) > 0
