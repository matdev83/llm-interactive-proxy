#!/usr/bin/env python3
"""
Test script to demonstrate model-specific reasoning configuration functionality.
This script shows how to configure and use model-specific reasoning defaults in the LLM interactive proxy.
"""

import json
import requests
import time
from typing import Dict, Any

# Proxy configuration
PROXY_URL = "http://localhost:8000"
API_KEY = "your-proxy-api-key"  # Replace with your actual proxy API key

def test_model_specific_reasoning_config():
    """Test model-specific reasoning configuration functionality."""
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    print("[BRAIN] Testing Model-Specific Reasoning Configuration")
    print("=" * 60)
    
    # Test cases for different scenarios
    test_cases = [
        {
            "name": "OpenAI O1 with High Reasoning Effort (from config)",
            "description": "Model configured with high reasoning effort by default",
            "model": "openrouter:openai/o1",
            "messages": [
                {"role": "user", "content": "Solve this step by step: What is the derivative of x^3 + 2x^2 - 5x + 1?"}
            ],
            "expected_reasoning": "high",
            "config_applied": True
        },
        {
            "name": "Gemini 2.5 Pro with Thinking Budget (from config)",
            "description": "Model configured with 2048 thinking budget by default",
            "model": "gemini:gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Analyze the pros and cons of renewable energy sources."}
            ],
            "expected_thinking_budget": 2048,
            "config_applied": True
        },
        {
            "name": "Override Config with Session Setting",
            "description": "Session-level setting should override model defaults",
            "model": "openrouter:openai/o1-mini",
            "commands": ["!/set(reasoning-effort=high)"],
            "messages": [
                {"role": "user", "content": "Explain quantum entanglement in simple terms."}
            ],
            "expected_reasoning": "high",  # Override from medium (config) to high (session)
            "config_applied": False  # Session override
        },
        {
            "name": "Direct API Parameter Override",
            "description": "Direct API parameters should take highest precedence",
            "model": "gemini:gemini-2.5-flash",
            "messages": [
                {"role": "user", "content": "What are the implications of artificial intelligence on society?"}
            ],
            "thinking_budget": 4096,  # Override config default of 1024
            "expected_thinking_budget": 4096,
            "config_applied": False  # Direct API override
        },
        {
            "name": "Model Without Config Defaults",
            "description": "Model not in config should work normally without defaults",
            "model": "openrouter:anthropic/claude-3.5-sonnet",
            "messages": [
                {"role": "user", "content": "Write a short story about a robot learning emotions."}
            ],
            "expected_reasoning": None,
            "config_applied": False
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n[CLIPBOARD] Test {i}: {test_case['name']}")
        print(f"Description: {test_case['description']}")
        print(f"Model: {test_case['model']}")
        
        # Execute any setup commands if specified
        if 'commands' in test_case:
            for command in test_case['commands']:
                command_payload = {
                    "model": test_case['model'],
                    "messages": [{"role": "user", "content": command}]
                }
                print(f"Executing command: {command}")
                try:
                    response = requests.post(
                        f"{PROXY_URL}/v1/chat/completions",
                        headers=headers,
                        json=command_payload,
                        timeout=30
                    )
                    if response.status_code == 200:
                        print("[CHECK] Command executed successfully")
                    else:
                        print(f"[WARNING] Command execution failed: {response.status_code}")
                except Exception as e:
                    print(f"[X] Command execution error: {e}")
        
        # Prepare the main request payload
        payload = {
            "model": test_case['model'],
            "messages": test_case['messages'],
            "max_tokens": 150  # Keep responses short for testing
        }
        
        # Add direct API parameters if specified
        if 'thinking_budget' in test_case:
            payload['thinking_budget'] = test_case['thinking_budget']
        if 'reasoning_effort' in test_case:
            payload['reasoning_effort'] = test_case['reasoning_effort']
        
        print(f"Request payload: {json.dumps(payload, indent=2)}")
        
        try:
            start_time = time.time()
            response = requests.post(
                f"{PROXY_URL}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60
            )
            end_time = time.time()
            
            print(f"⏱️ Response time: {end_time - start_time:.2f}s")
            print(f"[CHART] Status code: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                print("[CHECK] Request successful")
                
                # Check if reasoning was applied as expected
                if 'config_applied' in test_case and test_case['config_applied']:
                    print("[WRENCH] Model defaults should have been applied from configuration")
                elif 'config_applied' in test_case and not test_case['config_applied']:
                    print("[WRENCH] Model defaults should have been overridden")
                
                # Show response content (truncated)
                if 'choices' in response_data and response_data['choices']:
                    content = response_data['choices'][0]['message']['content']
                    print(f"📝 Response preview: {content[:100]}...")
                
                # Show usage information if available
                if 'usage' in response_data:
                    usage = response_data['usage']
                    print(f"📈 Token usage: {usage}")
                    
                    # Check for reasoning tokens (indicates reasoning was used)
                    if 'reasoning_tokens' in usage or any('reasoning' in str(usage).lower() for key in usage):
                        print("[BRAIN] Reasoning tokens detected - reasoning was applied!")
                
            else:
                print(f"[X] Request failed: {response.status_code}")
                print(f"Error details: {response.text}")
                
        except requests.exceptions.Timeout:
            print("⏰ Request timed out")
        except Exception as e:
            print(f"[X] Request error: {e}")
        
        print("-" * 50)
        time.sleep(1)  # Brief pause between tests

def demonstrate_config_structure():
    """Demonstrate the configuration file structure for model-specific reasoning."""
    
    print("\n📁 Model-Specific Reasoning Configuration Structure")
    print("=" * 60)
    
    sample_config = {
        "default_backend": "openrouter",
        "interactive_mode": True,
        "redact_api_keys_in_prompts": True,
        "command_prefix": "!/",
        "model_defaults": {
            # OpenAI models via OpenRouter
            "openrouter:openai/o1": {
                "reasoning": {
                    "reasoning_effort": "high"
                }
            },
            "openrouter:openai/o1-mini": {
                "reasoning": {
                    "reasoning_effort": "medium"
                }
            },
            "openrouter:openai/o3-mini": {
                "reasoning": {
                    "reasoning_effort": "high",
                    "reasoning": {
                        "effort": "high",
                        "max_tokens": 2000
                    }
                }
            },
            
            # DeepSeek models
            "openrouter:deepseek/deepseek-r1": {
                "reasoning": {
                    "reasoning": {
                        "effort": "medium",
                        "max_tokens": 1500
                    }
                }
            },
            
            # Gemini models
            "gemini:gemini-2.5-pro": {
                "reasoning": {
                    "thinking_budget": 2048,
                    "generation_config": {
                        "thinkingConfig": {
                            "thinkingBudget": 2048
                        },
                        "temperature": 0.7
                    }
                }
            },
            "gemini:gemini-2.5-flash": {
                "reasoning": {
                    "thinking_budget": 1024,
                    "generation_config": {
                        "thinkingConfig": {
                            "thinkingBudget": 1024
                        },
                        "temperature": 0.8
                    }
                }
            },
            
            # Short model names (match any backend)
            "gemini-exp-1206": {
                "reasoning": {
                    "thinking_budget": 4096
                }
            }
        },
        "failover_routes": {
            "reasoning-models": {
                "policy": "m",
                "elements": [
                    "openrouter:openai/o1",
                    "openrouter:openai/o3-mini",
                    "gemini:gemini-2.5-pro"
                ]
            }
        }
    }
    
    print("Configuration file format (save as config/reasoning-config.json):")
    print(json.dumps(sample_config, indent=2))
    
    print("\n[BOOKS] Configuration Explanation:")
    print("• model_defaults: Define default reasoning parameters per model")
    print("• Full model names: 'backend:model' (e.g., 'openrouter:openai/o1')")
    print("• Short model names: 'model' (e.g., 'gemini-exp-1206') - matches any backend")
    print("• reasoning.reasoning_effort: OpenAI-style effort levels (low/medium/high)")
    print("• reasoning.reasoning: OpenRouter unified reasoning config")
    print("• reasoning.thinking_budget: Gemini thinking tokens (128-32768)")
    print("• reasoning.generation_config: Full Gemini generation configuration")
    
    print("\n🔄 Precedence Order (highest to lowest):")
    print("1. Direct API parameters in request")
    print("2. Session-level settings (!/set commands)")
    print("3. Model-specific defaults (from config file)")
    print("4. No reasoning parameters")

def main():
    """Main test function."""
    print("🚀 Model-Specific Reasoning Configuration Test Suite")
    print("=" * 60)
    print("This script demonstrates the new model-specific reasoning")
    print("configuration functionality in the LLM Interactive Proxy.")
    print()
    print("Prerequisites:")
    print("• Proxy server running on http://localhost:8000")
    print("• Valid API key configured")
    print("• Configuration file with model defaults loaded")
    print("• OpenRouter and/or Gemini API keys configured")
    print()
    
    # Show configuration structure first
    demonstrate_config_structure()
    
    # Run the actual tests
    test_model_specific_reasoning_config()
    
    print("\n🎉 Test suite completed!")
    print("\nNext steps:")
    print("• Create your own config file based on the sample")
    print("• Start the proxy with: python -m src.main --config config/your-config.json")
    print("• Test with your preferred reasoning models")
    print("• Monitor reasoning token usage in responses")

if __name__ == "__main__":
    main() 