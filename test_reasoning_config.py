from src.core.domain.configuration.reasoning_config import ReasoningConfiguration

# Test default initialization
config = ReasoningConfiguration()
print("Default initialization:")
print(f"reasoning_effort: {config.reasoning_effort}")
print(f"thinking_budget: {config.thinking_budget}")
print(f"temperature: {config.temperature}")
print(f"reasoning_config: {config.reasoning_config}")
print(f"gemini_generation_config: {config.gemini_generation_config}")

# Test initialization with values
config_with_values = ReasoningConfiguration(
    reasoning_effort="high",
    thinking_budget=1024,
    temperature=0.7,
    reasoning_config={"max_tokens": 1000},
    gemini_generation_config={"top_p": 0.9},
)
print("\nInitialization with values:")
print(f"reasoning_effort: {config_with_values.reasoning_effort}")
print(f"thinking_budget: {config_with_values.thinking_budget}")
print(f"temperature: {config_with_values.temperature}")
print(f"reasoning_config: {config_with_values.reasoning_config}")
print(f"gemini_generation_config: {config_with_values.gemini_generation_config}")

# Test with_* methods
new_config = config_with_values.with_reasoning_effort("medium")
print("\nWith reasoning effort 'medium':")
print(f"reasoning_effort: {new_config.reasoning_effort}")
print(f"thinking_budget: {new_config.thinking_budget}")
print(f"temperature: {new_config.temperature}")
print(f"reasoning_config: {new_config.reasoning_config}")
print(f"gemini_generation_config: {new_config.gemini_generation_config}")
