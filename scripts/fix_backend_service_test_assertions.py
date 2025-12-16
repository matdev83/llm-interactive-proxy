from pathlib import Path

file_path = Path("tests/unit/core/services/test_backend_service_targeted.py")
content = file_path.read_text(encoding="utf-8")

# Update assertion to check manager's state
target = """    
        assert created_backends[0].shutdown_calls == 1
        assert len(service._per_session_backends) == 2
        assert "gemini-cli-acp:s1" not in service._per_session_backends
        assert all(
            key.startswith("gemini-cli-acp") for key in service._per_session_backends
        )"""

replacement = """
        assert created_backends[0].shutdown_calls == 1
        
        # Check against lifecycle manager state if present, otherwise service state
        backends_map = service._per_session_backends
        if hasattr(service, "_backend_lifecycle_manager"):
            backends_map = service._backend_lifecycle_manager._per_session_backends
            
        assert len(backends_map) == 2
        assert "gemini-cli-acp:s1" not in backends_map
        assert all(
            key.startswith("gemini-cli-acp") for key in backends_map
        )"""

if target in content:
    content = content.replace(target, replacement)
    file_path.write_text(content, encoding="utf-8")
    print(
        "Updated assertions in test_session_backend_cache_eviction_closes_old_backends"
    )
else:
    print("Could not find assertions to update")
    # Debug
    start_idx = content.find("assert created_backends[0].shutdown_calls == 1")
    if start_idx != -1:
        print("Context:", repr(content[start_idx : start_idx + 300]))
