import json
import asyncio
import httpx
import logging
import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

from src.core.config.app_config import AppConfig
from src.connectors.kiro_oauth_auto.connector import KiroOAuthAutoConnector
from src.core.services.translation_service import TranslationService
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import StreamingResponseEnvelope

async def main():
    # Setup logging to see what's happening
    logging.basicConfig(level=logging.INFO)
    
    # Initialize components
    config = AppConfig()
    translation_service = TranslationService()
    
    async with httpx.AsyncClient() as client:
        connector = KiroOAuthAutoConnector(
            client=client,
            config=config,
            translation_service=translation_service
        )
        
        print("Initializing Kiro connector...")
        await connector.initialize()
        
        available_models = connector.get_available_models()
        print(f"Available models: {available_models}")
        
        # Look for a haiku model
        model = next((m for m in available_models if "haiku" in m.lower()), "amazon/claude-haiku-4.5")
        print(f"Using model: {model}")
        
        request = CanonicalChatRequest(
            model=model,
            messages=[ChatMessage(role="user", content="Hello! Briefly introduce yourself.")],
            stream=True,
            session_id="demo-session"
        )
        
        canonical_request = ConnectorChatCompletionsRequest(
            request=request,
            processed_messages=list(request.messages),
            effective_model=model,
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None
        )
        
        print("\nSending request...\n")
        try:
            response = await connector.chat_completions(canonical_request)
            
            if isinstance(response, StreamingResponseEnvelope):
                print("Response (Streaming):")
                async for chunk in response.body_iterator:
                    # Chunks are SSE format: data: {...}\n\n
                    chunk_str = chunk.decode("utf-8")
                    for line in chunk_str.splitlines():
                        if line.startswith("data: "):
                            content_to_parse = line[6:].strip()
                            if content_to_parse == "[DONE]":
                                continue
                            try:
                                data = json.loads(content_to_parse)
                                content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                if content:
                                    print(content, end="", flush=True)
                            except json.JSONDecodeError:
                                # Skip lines that are not valid JSON (like meta-events)
                                continue
                print("\n")
            else:
                print("Response (Non-streaming):")
                print(response.content)
                
        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
