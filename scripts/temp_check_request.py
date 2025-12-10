"""Analyze the actual API format used by Antigravity vs Plan backends."""
import sys

sys.path.insert(0, '.')

import json
from pathlib import Path

from src.core.simulation.capture_reader import CaptureReader

reader = CaptureReader()
session = reader.load(Path('var/wire_captures_cbor/fcd4af7bf8e34d07b9d349d69603e02a.cbor'))

print("=" * 80)
print("COMPARING API FORMATS: PLAN vs ANTIGRAVITY")
print("=" * 80)

# Find a plan request and an antigravity request
plan_req_idx = None
antigravity_req_idx = None

for i, e in enumerate(session.entries):
    if 'CLIENT_TO_PROXY' in str(e.direction):
        d = e.data
        if isinstance(d, bytes):
            try:
                d = d.decode('utf-8')
                req = json.loads(d)
                model = req.get('model', '')
                if 'gemini-oauth-plan' in model and plan_req_idx is None:
                    plan_req_idx = i
                elif 'antigravity' in model and antigravity_req_idx is None:
                    antigravity_req_idx = i
            except:
                pass

print(f"\nPlan request index: {plan_req_idx}")
print(f"Antigravity request index: {antigravity_req_idx}")

# Check the PROXY_TO_BACKEND for each to see what format is sent
def analyze_request(label, client_idx):
    print(f"\n{'='*80}")
    print(f"{label} - OUTBOUND REQUEST FORMAT")
    print(f"{'='*80}")
    
    # Find the proxy-to-backend entry
    for i in range(client_idx, min(client_idx + 5, len(session.entries))):
        e = session.entries[i]
        direction = str(e.direction)
        if 'PROXY_TO_BACKEND' not in direction:
            continue
        
        d = e.data
        if isinstance(d, bytes):
            try:
                d_str = d.decode('utf-8')
            except:
                continue
        else:
            d_str = str(d)
        
        print(f"\n[{i}] PROXY_TO_BACKEND request:")
        
        # Try to parse as JSON
        try:
            req = json.loads(d_str)
            
            # Check format indicators
            has_messages = 'messages' in req
            has_contents = 'contents' in req
            has_generation_config = 'generationConfig' in req
            has_request_wrapper = 'request' in req
            
            print("  Format indicators:")
            print(f"    - has 'messages' (OpenAI): {has_messages}")
            print(f"    - has 'contents' (Gemini): {has_contents}")
            print(f"    - has 'generationConfig': {has_generation_config}")
            print(f"    - has 'request' wrapper (Code Assist): {has_request_wrapper}")
            
            if has_request_wrapper:
                inner = req.get('request', {})
                print(f"    - inner 'contents': {'contents' in inner}")
                print(f"    - inner 'generationConfig': {'generationConfig' in inner}")
                if 'generationConfig' in inner:
                    gen_cfg = inner['generationConfig']
                    print(f"    - generationConfig keys: {list(gen_cfg.keys())}")
                    if 'thinkingConfig' in gen_cfg:
                        print(f"    - thinkingConfig: {gen_cfg['thinkingConfig']}")
            
            # Show top-level keys
            print(f"\n  Top-level keys: {list(req.keys())}")
            
        except json.JSONDecodeError:
            print(f"  Raw (not JSON): {d_str[:500]}")
        
        break

# Now check the backend responses
def analyze_response(label, client_idx):
    print(f"\n{'-'*40}")
    print(f"{label} - BACKEND RESPONSE FORMAT")
    print(f"{'-'*40}")
    
    # Find backend responses
    for i in range(client_idx, min(client_idx + 20, len(session.entries))):
        e = session.entries[i]
        direction = str(e.direction)
        if 'BACKEND_TO_PROXY' not in direction:
            continue
        
        d = e.data
        if isinstance(d, bytes):
            try:
                d_str = d.decode('utf-8')
            except:
                continue
        else:
            d_str = str(d)
        
        if not d_str.strip() or d_str.strip() == 'data: [DONE]':
            continue
        
        print(f"\n[{i}] First non-empty backend response:")
        
        # Parse SSE
        for line in d_str.split('\n'):
            if line.startswith('data: ') and line.strip() != 'data: [DONE]':
                try:
                    payload = json.loads(line[6:])
                    
                    has_choices = 'choices' in payload
                    has_candidates = 'candidates' in payload
                    has_response = 'response' in payload
                    
                    print("  Format indicators:")
                    print(f"    - has 'choices' (OpenAI): {has_choices}")
                    print(f"    - has 'candidates' (Gemini native): {has_candidates}")
                    print(f"    - has 'response' wrapper: {has_response}")
                    
                    print("\n  Response (truncated):")
                    print(json.dumps(payload, indent=2)[:800])
                    
                except:
                    pass
                break
        break

# Run analysis for both
print("\n" + "=" * 80)
print("GEMINI-OAUTH-PLAN BACKEND")
print("=" * 80)
if plan_req_idx is not None:
    analyze_request("PLAN", plan_req_idx)
    analyze_response("PLAN", plan_req_idx)
else:
    print("No plan request found!")

print("\n" + "=" * 80)
print("GEMINI-OAUTH-ANTIGRAVITY BACKEND")
print("=" * 80)
if antigravity_req_idx is not None:
    analyze_request("ANTIGRAVITY", antigravity_req_idx)
    analyze_response("ANTIGRAVITY", antigravity_req_idx)
else:
    print("No antigravity request found!")
