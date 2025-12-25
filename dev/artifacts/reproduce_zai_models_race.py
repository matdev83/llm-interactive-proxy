"""
Repro script for zai connector _default_models list mutation
"""
import threading


def test_zai_default_models_race():
    """Test potential race condition in _default_models access"""
    
    class MockZAIConnector:
        def __init__(self):
            self._default_models = ["glm-4.5", "glm-4.5-flash", "glm-4.5-air"]
            self.available_models = []
        
        def get_available_models(self):
            # Copy to avoid modifying original
            if hasattr(self, 'available_models') and self.available_models:
                return self.available_models
            return self._default_models.copy()
        
        def _ensure_models_loaded(self):
            # This modifies available_models from config
            if not hasattr(self, "available_models"):
                self.available_models = []
            if self.available_models:
                return
            
            # Simulate loading from API
            self.available_models = self._default_models.copy()
    
    connector = MockZAIConnector()
    
    # Test concurrent access
    results = []
    threads = []
    
    def thread_func():
        models = connector.get_available_models()
        results.append(len(models))
        # Simulate modifying the list
        if models:
            models.append("test-model")
    
    for _ in range(10):
        t = threading.Thread(target=thread_func)
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    print(f"  Results: {results}")
    print(f"  Expected all 3, got varied results: {len(set(results)) > 1}")
    
    if len(set(results)) > 1:
        print("  RACE CONDITION CONFIRMED: Results varied due to concurrent access")
        return True
    
    print("  No race detected")
    return False

if __name__ == "__main__":
    print("Testing ZAI connector _default_models race...")
    if test_zai_default_models_race():
        exit(1)
    else:
        exit(0)
