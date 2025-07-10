#!/usr/bin/env python3
"""
Test script to demonstrate temperature configuration functionality.
This script shows how to configure and use temperature settings in the LLM interactive proxy.
"""

import json
import requests
import time
from typing import Dict, Any

# Proxy configuration
PROXY_URL = "http://localhost:8000"
API_KEY = "your-proxy-api-key"  # Replace with your actual proxy API key

def test_temperature_configuration():
    """Test temperature configuration functionality across different providers."""
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    print("🌡️ Testing Temperature Configuration")
    print("=" * 60)
    
    # Test cases for different temperature scenarios
    test_cases = [
        {
            "name": "OpenAI Model with Config Default Temperature",
            "description": "Model configured with temperature 0.3 by default",
            "model": "openrouter:openai/gpt-4",
            "messages": [
                {"role": "user", "content": "Write a creative short story about a robot discovering emotions. Keep it under 100 words."}
            ],
            "expected_temperature": 0.3,
            "config_applied": True
        },
        {
            "name": "Gemini Model with Config Default Temperature",
            "description": "Model configured with temperature 0.7 by default",
            "model": "gemini:gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Explain quantum computing in simple terms with creative analogies."}
            ],
            "expected_temperature": 0.7,
            "config_applied": True
        },
        {
            "name": "Session-Level Temperature Override",
            "description": "Session setting should override model defaults",
            "model": "openrouter:openai/gpt-4",
            "commands": ["!/set(temperature=0.9)"],
            "messages": [
                {"role": "user", "content": "Brainstorm 5 creative business ideas for the future."}
            ],
            "expected_temperature": 0.9,
            "config_applied": False  # Session override
        },
        {
            "name": "Direct API Temperature Override",
            "description": "Direct API parameters should take highest precedence",
            "model": "gemini:gemini-2.5-flash",
            "messages": [
                {"role": "user", "content": "Write a technical explanation of machine learning algorithms."}
            ],
            "temperature": 0.1,  # Very low for technical content
            "expected_temperature": 0.1,
            "config_applied": False  # Direct API override
        },
        {
            "name": "Gemini Temperature Clamping Test",
            "description": "Temperature > 1.0 should be clamped to 1.0 for Gemini",
            "model": "gemini:gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "Create a wildly imaginative fantasy story."}
            ],
            "temperature": 1.5,  # Should be clamped to 1.0
            "expected_temperature": 1.0,  # Clamped value
            "config_applied": False
        },
        {
            "name": "OpenAI High Temperature Test",
            "description": "OpenAI supports temperature up to 2.0",
            "model": "openrouter:openai/gpt-4",
            "messages": [
                {"role": "user", "content": "Generate the most creative and unusual poem you can imagine."}
            ],
            "temperature": 1.8,  # High creativity
            "expected_temperature": 1.8,
            "config_applied": False
        },
        {
            "name": "Zero Temperature (Deterministic)",
            "description": "Temperature 0.0 should produce consistent output",
            "model": "openrouter:openai/gpt-4",
            "messages": [
                {"role": "user", "content": "What is 2+2? Provide only the numerical answer."}
            ],
            "temperature": 0.0,
            "expected_temperature": 0.0,
            "config_applied": False
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n📋 Test {i}: {test_case['name']}")
        print(f"Description: {test_case['description']}")
        print(f"Model: {test_case['model']}")
        print(f"Expected Temperature: {test_case['expected_temperature']}")
        
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
                        print("✅ Command executed successfully")
                    else:
                        print(f"⚠️ Command execution failed: {response.status_code}")
                except Exception as e:
                    print(f"❌ Command execution error: {e}")
        
        # Prepare the main request payload
        payload = {
            "model": test_case['model'],
            "messages": test_case['messages'],
            "max_tokens": 150  # Keep responses short for testing
        }
        
        # Add direct API temperature if specified
        if 'temperature' in test_case:
            payload['temperature'] = test_case['temperature']
        
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
            print(f"📊 Status code: {response.status_code}")
            
            if response.status_code == 200:
                response_data = response.json()
                print("✅ Request successful")
                
                # Check if temperature was applied as expected
                if 'config_applied' in test_case and test_case['config_applied']:
                    print("🔧 Model defaults should have been applied from configuration")
                elif 'config_applied' in test_case and not test_case['config_applied']:
                    print("🔧 Model defaults should have been overridden")
                
                # Show response content (truncated)
                if 'choices' in response_data and response_data['choices']:
                    content = response_data['choices'][0]['message']['content']
                    print(f"📝 Response preview: {content[:100]}...")
                
                # Show usage information if available
                if 'usage' in response_data:
                    usage = response_data['usage']
                    print(f"📈 Token usage: {usage}")
                
                # Analyze response creativity/determinism based on temperature
                if test_case['expected_temperature'] == 0.0:
                    print("🎯 Expected: Deterministic, factual response")
                elif test_case['expected_temperature'] <= 0.3:
                    print("🎯 Expected: Conservative, focused response")
                elif test_case['expected_temperature'] <= 0.7:
                    print("🎯 Expected: Balanced creativity and coherence")
                elif test_case['expected_temperature'] <= 1.0:
                    print("🎯 Expected: High creativity and variety")
                else:
                    print("🎯 Expected: Maximum creativity (OpenAI only)")
                
            else:
                print(f"❌ Request failed: {response.status_code}")
                print(f"Error details: {response.text}")
                
        except requests.exceptions.Timeout:
            print("⏰ Request timed out")
        except Exception as e:
            print(f"❌ Request error: {e}")
        
        print("-" * 50)
        time.sleep(1)  # Brief pause between tests

def demonstrate_temperature_config_structure():
    """Demonstrate the configuration file structure for temperature settings."""
    
    print("\n🌡️ Temperature Configuration Structure")
    print("=" * 60)
    
    sample_config = {
        "default_backend": "openrouter",
        "interactive_mode": True,
        "redact_api_keys_in_prompts": True,
        "command_prefix": "!/",
        "model_defaults": {
            # Conservative models for factual tasks
            "openrouter:openai/gpt-4": {
                "reasoning": {
                    "temperature": 0.3
                }
            },
            "openrouter:anthropic/claude-3.5-sonnet": {
                "reasoning": {
                    "temperature": 0.4
                }
            },
            
            # Balanced models for general use
            "gemini:gemini-2.5-pro": {
                "reasoning": {
                    "thinking_budget": 2048,
                    "temperature": 0.7
                }
            },
            "openrouter:openai/gpt-4o": {
                "reasoning": {
                    "temperature": 0.7
                }
            },
            
            # Creative models for brainstorming
            "openrouter:openai/gpt-4-turbo": {
                "reasoning": {
                    "temperature": 0.9
                }
            },
            "gemini:gemini-2.5-flash": {
                "reasoning": {
                    "thinking_budget": 1024,
                    "temperature": 0.8
                }
            },
            
            # Reasoning models with lower temperature for accuracy
            "openrouter:openai/o1": {
                "reasoning": {
                    "reasoning_effort": "high",
                    "temperature": 0.2
                }
            },
            "openrouter:deepseek/deepseek-r1": {
                "reasoning": {
                    "reasoning": {
                        "effort": "medium",
                        "max_tokens": 1500
                    },
                    "temperature": 0.3
                }
            }
        },
        "failover_routes": {
            "creative-models": {
                "policy": "m",
                "elements": [
                    "openrouter:openai/gpt-4-turbo",
                    "gemini:gemini-2.5-flash"
                ]
            },
            "analytical-models": {
                "policy": "m",
                "elements": [
                    "openrouter:openai/o1",
                    "openrouter:anthropic/claude-3.5-sonnet"
                ]
            }
        }
    }
    
    print("Configuration file format (save as config/temperature-config.json):")
    print(json.dumps(sample_config, indent=2))
    
    print("\n📚 Temperature Configuration Explanation:")
    print("• temperature: Controls output randomness (0.0-2.0 for OpenAI, 0.0-1.0 for Gemini)")
    print("• Lower values (0.0-0.3): More deterministic, factual responses")
    print("• Medium values (0.4-0.7): Balanced creativity and coherence")
    print("• Higher values (0.8-1.0): More creative and varied responses")
    print("• Very high values (1.1-2.0): Maximum creativity (OpenAI only)")
    
    print("\n🔄 Precedence Order (highest to lowest):")
    print("1. Direct API parameters in request")
    print("2. Session-level settings (!/set(temperature=...))")
    print("3. Model-specific defaults (from config file)")
    print("4. Provider defaults")
    
    print("\n🎯 Use Case Examples:")
    print("• Code generation: temperature=0.1-0.3")
    print("• Technical documentation: temperature=0.2-0.4")
    print("• General conversation: temperature=0.6-0.8")
    print("• Creative writing: temperature=0.8-1.2")
    print("• Brainstorming: temperature=1.0-1.5")

def test_temperature_commands():
    """Test temperature-related interactive commands."""
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    print("\n🎮 Testing Temperature Commands")
    print("=" * 60)
    
    commands_to_test = [
        "!/set(temperature=0.5)",
        "!/set(temperature=1.0)",
        "!/set(temperature=0.0)",
        "!/unset(temperature)"
    ]
    
    for command in commands_to_test:
        print(f"\n🔧 Testing command: {command}")
        
        payload = {
            "model": "openrouter:gpt-4",
            "messages": [{"role": "user", "content": command}]
        }
        
        try:
            response = requests.post(
                f"{PROXY_URL}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                response_data = response.json()
                if 'choices' in response_data and response_data['choices']:
                    content = response_data['choices'][0]['message']['content']
                    print(f"✅ Command result: {content}")
                else:
                    print("✅ Command executed successfully")
            else:
                print(f"❌ Command failed: {response.status_code}")
                print(f"Error: {response.text}")
                
        except Exception as e:
            print(f"❌ Command error: {e}")

def main():
    """Main test function."""
    print("🚀 Temperature Configuration Test Suite")
    print("=" * 60)
    print("This script demonstrates the new temperature configuration")
    print("functionality in the LLM Interactive Proxy.")
    print()
    print("Prerequisites:")
    print("• Proxy server running on http://localhost:8000")
    print("• Valid API key configured")
    print("• Configuration file with model defaults loaded")
    print("• OpenRouter and/or Gemini API keys configured")
    print()
    
    # Show configuration structure first
    demonstrate_temperature_config_structure()
    
    # Test interactive commands
    test_temperature_commands()
    
    # Run the actual temperature tests
    test_temperature_configuration()
    
    print("\n🎉 Temperature test suite completed!")
    print("\nNext steps:")
    print("• Create your own config file with temperature defaults")
    print("• Start the proxy with: python -m src.main --config config/your-config.json")
    print("• Test with different temperature values for different use cases")
    print("• Monitor how temperature affects response creativity and consistency")

if __name__ == "__main__":
    main() 