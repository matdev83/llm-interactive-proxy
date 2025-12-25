import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.codebuff.connection_manager import ConnectionManager

async def test_manual():
    print("Initializing manager...")
    manager = ConnectionManager()
    topic = "test-topic"
    
    print("Calling get_subscribers...")
    result = await manager.get_subscribers(topic)
    
    print(f"Result type: {type(result)}")
    print(f"Result: {result}")
    
    if isinstance(result, list):
        print("Result is a list. OK.")
    else:
        print("Result is NOT a list.")

if __name__ == "__main__":
    asyncio.run(test_manual())
