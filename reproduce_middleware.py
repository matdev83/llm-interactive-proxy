
import asyncio
from dataclasses import dataclass
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallReactor,
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware
from src.core.domain.responses import ProcessedResponse

@dataclass
class MockResponse:
    content: str
    tool_calls: list[dict]
    metadata: dict = None

class MockReactor(IToolCallReactor):
    async def register_handler(self, handler): pass
    async def unregister_handler(self, handler_name): pass
    def get_registered_handlers(self): return []
    
    async def process_tool_call(self, context: ToolCallContext) -> ToolCallReactionResult | None:
        return ToolCallReactionResult(
            should_swallow=True,
            replacement_response="Steering Message",
            metadata={"handler": "test"}
        )

async def main():
    reactor = MockReactor()
    middleware = ToolCallReactorMiddleware(reactor)
    
    original_response = MockResponse(
        content="original",
        tool_calls=[{"function": {"name": "pytest", "arguments": "{}"}}],
        metadata={}
    )
    
    context = {"backend_name": "test", "model_name": "test"}
    
    result = await middleware.process(original_response, "session-1", context)
    
    print(f"Result type: {type(result)}")
    if isinstance(result, ProcessedResponse):
        print(f"Metadata: {result.metadata}")
        if result.metadata.get("steering_message") == "Steering Message":
            print("SUCCESS: Steering message found in metadata")
        else:
            print("FAILURE: Steering message missing or incorrect")
            
if __name__ == "__main__":
    asyncio.run(main())
