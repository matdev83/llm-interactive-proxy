#!/usr/bin/env python3
"""
Test ZAI backend directly without going through the backend factory that adds test keys.
"""
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

async def test_zai_direct():
    """Test ZAI backend directly with real API key"""
    print("🚀 ZAI BACKEND DIRECT TEST - REAL API KEY")
    print("=" * 50)
    
    # Check if ZAI API key is available
    zai_api_key = os.environ.get("ZAI_API_KEY")
    if not zai_api_key:
        print("❌ ZAI_API_KEY environment variable not set!")
        return False
    
    print(f"🔑 Using real ZAI API key: {zai_api_key[:20]}...")
    
    # Generate unique prompt with timestamp
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    unique_number = hash(current_time) % 10000
    
    unique_prompt = f"""Write a Python function called 'add_{unique_number}' that adds {unique_number} and 5, returning {unique_number + 5}. Include a docstring. Timestamp: {current_time}"""
    
    print("📝 Unique prompt details:")
    print(f"   Timestamp: {current_time}")
    print(f"   Unique number: {unique_number}")
    print(f"   Expected result: {unique_number + 5}")
    print(f"   Task: Create add_{unique_number} function")
    print()
    
    try:
        # Import required services and create backend directly
        import httpx
        from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
        from src.core.config.app_config import AppConfig
        from src.core.domain.chat import ChatMessage, ChatRequest
        from src.core.services.translation_service import TranslationService
        
        # Create required dependencies
        config = AppConfig()
        client = httpx.AsyncClient()
        translation_service = TranslationService()
        
        print("🔧 Initializing ZAI backend directly with real API key...")
        
        # Initialize the backend directly with real API key
        backend = ZaiCodingPlanBackend(client=client, config=config, translation_service=translation_service)
        await backend.initialize(api_key=zai_api_key)
        
        print(f"✅ Backend initialized with API key: {backend.api_key[:20]}...")
        print(f"✅ Base URL: {backend.anthropic_api_base_url}")
        print(f"✅ Auth header: {backend.auth_header_name}")
        
        # Create request
        request = ChatRequest(
            model="claude-sonnet-4-20250514",
            messages=[ChatMessage(role="user", content=unique_prompt)],
            max_tokens=1000,
            temperature=0.7
        )
        
        # Process messages (should be ChatMessage objects)
        processed_messages = [ChatMessage(role="user", content=unique_prompt)]
        effective_model = "claude-sonnet-4-20250514"
        
        print("📡 Sending request directly to ZAI servers...")
        
        try:
            response = await backend.chat_completions(
                request_data=request,
                processed_messages=processed_messages,
                effective_model=effective_model
            )
        finally:
            await client.aclose()
        
        if response and hasattr(response, 'content') and hasattr(response.content, 'choices'):
            content = response.content.choices[0].message.content
            
            print("✅ SUCCESS - Direct response from ZAI!")
            print(f"📊 Model: {response.content.model}")
            print(f"📈 Usage: {getattr(response.content, 'usage', 'N/A')}")
            print()
            print("📝 Response content:")
            print("=" * 60)
            print(content)
            print("=" * 60)
            print()
            
            # Check if this is the generic mock response
            if content.strip() == "Hello from ZAI!":
                print("❌ MOCK DETECTED: Response is 'Hello from ZAI!' - this is still mocked!")
                print("❌ There may be HTTP mocking happening at a lower level")
                return False
            
            # Analyze response for contextual proof
            proofs = []
            
            if f"add_{unique_number}" in content:
                proofs.append(f"✅ Contains exact function name 'add_{unique_number}'")
            
            if str(unique_number) in content:
                proofs.append(f"✅ Contains our unique number {unique_number}")
                
            if str(unique_number + 5) in content:
                proofs.append(f"✅ Contains expected result {unique_number + 5}")
                
            if "def " in content and "add" in content:
                proofs.append("✅ Contains Python function definition with add")
                
            if current_time[:10] in content:
                proofs.append("✅ References the current timestamp")
            
            print("🎯 CONTEXTUAL ANALYSIS:")
            for proof in proofs:
                print(f"   {proof}")
            
            if len(proofs) >= 2:
                print()
                print("🏆 SUCCESS: ZAI backend is FULLY FUNCTIONAL!")
                print("   ✅ Sends correct prompts to ZAI servers")
                print("   ✅ Receives contextual responses")
                print("   ✅ Real API communication working")
                return True
            else:
                print()
                print("⚠️  Response not contextual - may still have issues")
                print(f"   Expected: add_{unique_number}, {unique_number}, {unique_number + 5}")
                return False
                
        else:
            print("❌ No valid response received from backend")
            return False
                
    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    print("🔬 ZAI BACKEND DIRECT TEST - BYPASS FACTORY")
    print("=" * 70)
    print("Testing ZAI backend directly with real API key, bypassing test factory.")
    print()
    
    success = await test_zai_direct()
    
    if success:
        print("\n🎉 ZAI BACKEND IS FUNCTIONAL!")
        print("✅ Direct communication with ZAI servers working")
        print("✅ Sends correct prompts and receives contextual responses")
        print("✅ Backend implementation is correct")
    else:
        print("\n❌ ZAI BACKEND STILL HAS ISSUES!")
        print("❌ Need to investigate further")
    
    return success

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
