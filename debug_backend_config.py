from src.core.domain.configuration.backend_config import BackendConfiguration

def test_backend_config():
    # Create a backend config
    config = BackendConfiguration()
    print(f"Initial model: {config.model}")
    print(f"Initial dump: {config.model_dump()}")
    
    # Set a model
    new_config = config.with_model("gpt-4")
    print(f"New config model: {new_config.model}")
    print(f"New config dump: {new_config.model_dump()}")
    
    # Check if they're the same object
    print(f"Same object: {config is new_config}")
    
    # Check the update dict
    print(f"Update dict: {{'model': 'gpt-4'}}")
    
    # Try model_copy directly
    copied_config = config.model_copy(update={"model": "gpt-4"})
    print(f"Copied config model: {copied_config.model}")
    print(f"Copied config dump: {copied_config.model_dump()}")
    
    # Try creating a new instance with the model set
    new_instance = BackendConfiguration(model="gpt-4")
    print(f"New instance model: {new_instance.model}")
    print(f"New instance dump: {new_instance.model_dump()}")

if __name__ == "__main__":
    test_backend_config()