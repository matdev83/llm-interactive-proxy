import argparse
import sys
import requests
import json
import time

def check_health(url):
    print(f"Checking health at {url}/internal/health...")
    try:
        resp = requests.get(f"{url}/internal/health", timeout=5)
        if resp.status_code == 200:
            print("✅ Health check passed")
            return True
        else:
            print(f"❌ Health check failed: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

def check_completion(url, model, api_key="dummy"):
    print(f"Checking completion for model {model}...")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": "Say 'test passed'"}],
        "max_tokens": 10
    }
    
    try:
        resp = requests.post(
            f"{url}/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        
        if resp.status_code == 200:
            content = resp.json()
            if "choices" in content and len(content["choices"]) > 0:
                print(f"✅ Completion passed for {model}")
                return True
            else:
                print(f"❌ Completion failed for {model}: Invalid response format")
                return False
        else:
            print(f"❌ Completion failed for {model}: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Completion failed for {model}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Verify LLM Proxy Deployment")
    parser.add_argument("--url", default="http://localhost:8000", help="Proxy URL")
    parser.add_argument("--key", default="dummy", help="API Key for proxy")
    parser.add_argument("--model", default="gpt-3.5-turbo", help="Model to test")
    args = parser.parse_args()
    
    print(f"Verifying deployment at {args.url}")
    
    if not check_health(args.url):
        sys.exit(1)
        
    if not check_completion(args.url, args.model, args.key):
        sys.exit(1)
        
    print("\n🎉 All checks passed!")

if __name__ == "__main__":
    main()
