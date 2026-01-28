import asyncio
import json
import os
import sys

# Add current directory to sys.path to ensure src is importable
sys.path.append(os.getcwd())

# Import required components from the project
from src.core.domain.chat import ChatRequest, ChatMessage
from src.core.services.backend_service import BackendService
from src.core.di.services import register_core_services, get_service_collection
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.services.streaming.chunk_normalizer import ProcessedChunkContent

async def run_demo():
    print("=== Kimi Code Backend End-to-End Demo ===")
    
    # 1. Setup environment and configuration
    if not os.getenv("KIMI_API_KEY"):
        print("Error: KIMI_API_KEY environment variable is not set.")
        return

    # 2. Initialize Service Provider and BackendService
    services = get_service_collection()
    register_core_services(services)
    provider = services.build_service_provider()
    
    backend_service = provider.get_required_service(BackendService)
    
    # 3. Prepare the ChatRequest
    model_string = "kimi-code:kimi/kimi-for-coding"
    
    messages = [
        ChatMessage(role="user", content="Write a simple hello world function in Python.")
    ]
    
    request = ChatRequest(
        model=model_string,
        messages=messages,
        max_tokens=100,
        stream=True
    )
    
    print(f"Sending prompt to model: {model_string}")
    print(f"Prompt: {messages[0].content}")
    print("-" * 40)
    
    # 4. Execute the request
    try:
        response_envelope = await backend_service.chat_completions(request)
        
        if isinstance(response_envelope, StreamingResponseEnvelope):
            print("Response received! Monitoring stream...")
            async for chunk in response_envelope.content:
                content = chunk.content
                if isinstance(content, ProcessedChunkContent):
                    data = content.data
                    if isinstance(data, dict):
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                print(text, end="", flush=True)
                elif isinstance(content, dict):
                    choices = content.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            print(text, end="", flush=True)
            print("\n" + "-" * 40)
            print("Stream finished.")
        else:
            print("Received non-streaming response:")
            print(json.dumps(response_envelope.content, indent=2))
            
    except Exception as e:
        print(f"\nError: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(run_demo())
