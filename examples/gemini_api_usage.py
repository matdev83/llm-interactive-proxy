"""
Example usage of the Gemini API compatibility interface.

This demonstrates how to use the LLM Interactive Proxy as if it were
the Google Gemini API, with proper request/response formats.
"""
import requests
import json
from typing import Dict, Any


class GeminiAPIClient:
    """
    Example client for interacting with the LLM Interactive Proxy 
    using Gemini API format.
    """
    
    def __init__(self, base_url: str, api_key: str):
        """
        Initialize the Gemini API client.
        
        Args:
            base_url: Base URL of the LLM Interactive Proxy (e.g., "http://localhost:8000")
            api_key: API key for authentication
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Gemini API requests."""
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,  # Gemini-style auth header
            # Fallback to Bearer token if needed
            "Authorization": f"Bearer {self.api_key}"
        }
    
    def list_models(self) -> Dict[str, Any]:
        """
        List available models in Gemini API format.
        
        Returns:
            Dictionary containing models list in Gemini format
        """
        url = f"{self.base_url}/v1beta/models"
        response = self.session.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()
    
    def generate_content(self, model: str, contents: list, **kwargs) -> Dict[str, Any]:
        """
        Generate content using Gemini API format.
        
        Args:
            model: Model name (e.g., "gemini-pro", "openrouter:gpt-4")
            contents: List of content objects in Gemini format
            **kwargs: Additional generation parameters
            
        Returns:
            Generated response in Gemini format
        """
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        
        payload = {
            "contents": contents,
            **kwargs
        }
        
        response = self.session.post(url, headers=self._get_headers(), json=payload)
        response.raise_for_status()
        return response.json()
    
    def stream_generate_content(self, model: str, contents: list, **kwargs):
        """
        Generate content with streaming using Gemini API format.
        
        Args:
            model: Model name
            contents: List of content objects in Gemini format
            **kwargs: Additional generation parameters
            
        Yields:
            Streaming response chunks in Gemini format
        """
        url = f"{self.base_url}/v1beta/models/{model}:streamGenerateContent"
        
        payload = {
            "contents": contents,
            **kwargs
        }
        
        response = self.session.post(
            url, 
            headers=self._get_headers(), 
            json=payload,
            stream=True
        )
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    data_str = line_str[6:]  # Remove 'data: ' prefix
                    if data_str.strip() == '[DONE]':
                        break
                    try:
                        yield json.loads(data_str)
                    except json.JSONDecodeError:
                        continue


def main():
    """Example usage of the Gemini API client."""
    
    # Initialize client
    # Replace with your actual proxy URL and API key
    client = GeminiAPIClient(
        base_url="http://localhost:8000",
        api_key="your-api-key-here"
    )
    
    print("=== Gemini API Compatibility Example ===\n")
    
    # 1. List available models
    print("1. Listing available models...")
    try:
        models = client.list_models()
        print(f"Found {len(models.get('models', []))} models:")
        for model in models.get('models', [])[:3]:  # Show first 3
            print(f"  - {model['name']} ({model['display_name']})")
        print()
    except Exception as e:
        print(f"Error listing models: {e}\n")
    
    # 2. Simple content generation
    print("2. Simple content generation...")
    try:
        response = client.generate_content(
            model="gemini-pro",  # Use any available model
            contents=[
                {
                    "parts": [{"text": "What is the capital of France?"}],
                    "role": "user"
                }
            ],
            generation_config={
                "temperature": 0.7,
                "max_output_tokens": 100
            }
        )
        
        if response.get('candidates'):
            content = response['candidates'][0]['content']['parts'][0]['text']
            print(f"Response: {content}")
        print()
    except Exception as e:
        print(f"Error generating content: {e}\n")
    
    # 3. Content generation with system instruction
    print("3. Content generation with system instruction...")
    try:
        response = client.generate_content(
            model="gemini-pro",
            contents=[
                {
                    "parts": [{"text": "Explain quantum computing"}],
                    "role": "user"
                }
            ],
            system_instruction={
                "parts": [{"text": "You are a physics professor. Explain concepts clearly and simply."}],
                "role": "user"
            },
            generation_config={
                "temperature": 0.5,
                "max_output_tokens": 200
            }
        )
        
        if response.get('candidates'):
            content = response['candidates'][0]['content']['parts'][0]['text']
            print(f"Response: {content[:200]}...")
        print()
    except Exception as e:
        print(f"Error with system instruction: {e}\n")
    
    # 4. Streaming content generation
    print("4. Streaming content generation...")
    try:
        print("Streaming response: ", end="", flush=True)
        for chunk in client.stream_generate_content(
            model="gemini-pro",
            contents=[
                {
                    "parts": [{"text": "Write a short poem about programming"}],
                    "role": "user"
                }
            ],
            generation_config={
                "temperature": 0.8,
                "max_output_tokens": 150
            }
        ):
            if chunk.get('candidates'):
                candidate = chunk['candidates'][0]
                if candidate.get('content') and candidate['content'].get('parts'):
                    text = candidate['content']['parts'][0].get('text', '')
                    print(text, end="", flush=True)
        print("\n")
    except Exception as e:
        print(f"Error with streaming: {e}\n")
    
    # 5. Multi-turn conversation
    print("5. Multi-turn conversation...")
    try:
        conversation_contents = [
            {
                "parts": [{"text": "Hello! What's your name?"}],
                "role": "user"
            },
            {
                "parts": [{"text": "Hello! I'm an AI assistant. How can I help you today?"}],
                "role": "model"
            },
            {
                "parts": [{"text": "Can you help me with Python programming?"}],
                "role": "user"
            }
        ]
        
        response = client.generate_content(
            model="gemini-pro",
            contents=conversation_contents,
            generation_config={
                "temperature": 0.6,
                "max_output_tokens": 150
            }
        )
        
        if response.get('candidates'):
            content = response['candidates'][0]['content']['parts'][0]['text']
            print(f"Assistant: {content}")
        print()
    except Exception as e:
        print(f"Error with conversation: {e}\n")
    
    print("=== Example completed ===")


if __name__ == "__main__":
    main() 