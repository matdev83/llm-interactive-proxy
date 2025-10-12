import json
import os
import sys

from openai import OpenAI


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python test_client.py <config_path>")
        sys.exit(1)

    config_path = sys.argv[1]

    # Validate config file exists
    if not os.path.exists(config_path):
        print(f"Error: Configuration file '{config_path}' does not exist")
        sys.exit(1)

    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in configuration file '{config_path}': {e}")
        sys.exit(1)
    except OSError as e:
        print(f"Error: Could not read configuration file '{config_path}': {e}")
        sys.exit(1)

    # Validate required configuration fields
    required_fields = ["api_base", "model", "prompts"]
    missing_fields = [field for field in required_fields if field not in config]
    if missing_fields:
        print(f"Error: Missing required fields in config: {missing_fields}")
        sys.exit(1)

    if not isinstance(config["prompts"], list) or len(config["prompts"]) == 0:
        print("Error: 'prompts' must be a non-empty list in config")
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY_1")
    if not api_key:
        print("Error: GEMINI_API_KEY or GEMINI_API_KEY_1 environment variable not set")
        sys.exit(1)

    try:
        client = OpenAI(api_key=api_key, base_url=config["api_base"])
    except Exception as e:
        print(f"Error: Failed to initialize OpenAI client: {e}")
        sys.exit(1)

    for prompt in config["prompts"]:
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                model=config["model"],
            )
            print(chat_completion.choices[0].message.content)
            print("---")  # Separator between responses
        except Exception as e:
            print(f"Error: Failed to get completion for prompt '{prompt[:50]}...': {e}")
            continue


if __name__ == "__main__":
    main()
