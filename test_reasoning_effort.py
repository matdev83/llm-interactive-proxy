#!/usr/bin/env python3
"""
Simple test script to demonstrate provider-specific reasoning functionality.
This script shows how to use the reasoning features for different providers in the LLM interactive proxy.
"""

import json
import requests
import time
from typing import Dict, Any

# Proxy configuration
PROXY_URL = "http://localhost:8000"
API_KEY = "your-proxy-api-key"  # Replace with your actual proxy API key

def test_provider_specific_reasoning():
    """Test provider-specific reasoning functionality with different configurations."""
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Test cases for different providers and reasoning configurations
    test_cases = [
        {
            "name": "OpenAI reasoning effort via OpenRouter",
            "payload": {
                "model": "openrouter:openai/o1-preview",
                "messages": [{"role": "user", "content": "Solve this step by step: What is the derivative of x^3 + 2x^2 - 5x + 3?"}],
                "reasoning_effort": "high"
            }
        },
        {
            "name": "OpenRouter unified reasoning",
            "payload": {
                "model": "openrouter:deepseek/deepseek-r1",
                "messages": [{"role": "user", "content": "Analyze the pros and cons of renewable energy sources."}],
                "reasoning": {
                    "effort": "medium",
                    "max_tokens": 2000,
                    "exclude": False
                }
            }
        },
        {
            "name": "Gemini thinking budget",
            "payload": {
                "model": "gemini:gemini-2.5-pro",
                "messages": [{"role": "user", "content": "Design a simple recommendation system for a bookstore."}],
                "thinking_budget": 1024
            }
        },
        {
            "name": "Gemini generation config with thinking",
            "payload": {
                "model": "gemini:gemini-2.5-flash",
                "messages": [{"role": "user", "content": "Explain the concept of machine learning to a 10-year-old."}],
                "generation_config": {
                    "thinkingConfig": {
                        "thinkingBudget": 512
                    },
                    "temperature": 0.7
                }
            }
        },
        {
            "name": "OpenRouter extra params reasoning",
            "payload": {
                "model": "openrouter:qwen/qwq-32b-preview",
                "messages": [{"role": "user", "content": "What are the key principles of good software architecture?"}],
                "extra_params": {
                    "reasoning": {
                        "effort": "high",
                        "max_tokens": 1500
                    }
                }
            }
        },
        {
            "name": "Gemini extra params reasoning",
            "payload": {
                "model": "gemini:gemini-2.5-pro",
                "messages": [{"role": "user", "content": "Compare different sorting algorithms and their time complexities."}],
                "extra_params": {
                    "generationConfig": {
                        "thinkingConfig": {
                            "thinkingBudget": 2048
                        },
                        "temperature": 0.5
                    }
                }
            }
        },
        {
            "name": "In-chat reasoning command",
            "payload": {
                "model": "openrouter:openai/o1-mini",
                "messages": [{"role": "user", "content": "!/set(reasoning-effort=high) What are the benefits of renewable energy?"}]
            }
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        
        try:
            # Make request to proxy
            response = requests.post(
                f"{PROXY_URL}/v1/chat/completions",
                headers=headers,
                json=test_case["payload"],
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Extract response content
                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]
                    # Success - content received
                    
                    # Check usage information if available
                    usage = result.get("usage", {})
                    if usage:
                        # Usage information available
                        
                        # Check for reasoning tokens in usage
                        if "reasoning_tokens" in str(usage):
                            # Reasoning tokens detected in response
                            pass
                    
                    # Check provider-specific information
                    provider_info = result.get("provider_info", {})
                    if provider_info:
                        # Provider information available
                        pass
                        
                else:
                    # No choices in response
                    pass
                    
            else:
                # HTTP error occurred
                pass
                
        except requests.exceptions.RequestException as e:
            # Request failed
            pass
            
        except Exception as e:
            # Unexpected error
            pass
            
        # Small delay between requests
        time.sleep(1)

def test_in_chat_reasoning_commands():
    """Demonstrate in-chat reasoning commands for different providers."""
    
    # Example commands for different providers
    commands = [
        # OpenAI/OpenRouter commands
        "!/set(reasoning-effort=high)",
        "!/set(reasoning=effort=medium)",
        "!/set(reasoning=max_tokens=2000)",
        "!/set(reasoning=effort=low,exclude=true)",
        "!/unset(reasoning-effort)",
        "!/unset(reasoning)",
        
        # Gemini commands
        "!/set(thinking-budget=2048)",
        "!/set(gemini-generation-config={'thinkingConfig': {'thinkingBudget': 1024}})",
        "!/unset(thinking-budget)",
        "!/unset(gemini-generation-config)",
    ]
    
    # Available reasoning commands are defined in the commands list
    # Example conversation flow would demonstrate the commands in action

if __name__ == "__main__":
    try:
        test_provider_specific_reasoning()
        test_in_chat_reasoning_commands()
        
    except KeyboardInterrupt:
        # Test interrupted by user
        pass
    except Exception as e:
        # Test failed with error
        pass 