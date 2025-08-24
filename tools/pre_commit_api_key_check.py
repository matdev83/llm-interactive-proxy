import subprocess
import sys
import types
from pathlib import Path

import yaml

# Add the project root to the sys.path to import project modules
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from src.core.common.logging_utils import discover_api_keys_from_config_and_env


def load_config_from_yaml(config_path: Path):
    """Loads configuration from a YAML file and converts it to a SimpleNamespace object."""
    with open(config_path) as f:
        config_dict = yaml.safe_load(f)

    # Convert dictionary to a SimpleNamespace to mimic object access
    def dict_to_namespace(d):
        if isinstance(d, dict):
            return types.SimpleNamespace(
                **{k: dict_to_namespace(v) for k, v in d.items()}
            )
        return d

    return dict_to_namespace(config_dict)


def get_staged_files_content():
    """Returns a dictionary of staged file paths and their content."""
    try:
        # Get names of staged files
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        staged_files = result.stdout.strip().split("\n")
        if not staged_files or staged_files == [
            ""
        ]:  # Handle case where no files are staged
            return {}

        file_contents = {}
        for file_path in staged_files:
            if file_path:
                full_path = project_root / file_path
                if full_path.is_file():
                    try:
                        with open(full_path, encoding="utf-8") as f:
                            file_contents[file_path] = f.read()
                    except Exception as e:
                        print(
                            f"Warning: Could not read file {file_path}: {e}",
                            file=sys.stderr,
                        )
        return file_contents
    except subprocess.CalledProcessError as e:
        print(f"Error getting staged files: {e}", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        return {}


def main():
    config_path = project_root / "config.example.yaml"
    if not config_path.exists():
        print(f"Error: config.example.yaml not found at {config_path}", file=sys.stderr)
        sys.exit(1)

    config_obj = load_config_from_yaml(config_path)

    # Discover API keys from the loaded config and environment variables
    # Note: Environment variables will be those of the pre-commit hook's execution environment
    discovered_api_keys = discover_api_keys_from_config_and_env(config_obj)

    if not discovered_api_keys:
        print("No API keys discovered from config or environment. Skipping check.")
        sys.exit(0)

    print(f"Discovered {len(discovered_api_keys)} potential API keys for checking.")

    staged_files_content = get_staged_files_content()
    if not staged_files_content:
        print("No files staged for commit. Skipping check.")
        sys.exit(0)

    found_keys_in_staged_files = False
    placeholder_keys = ["your-api-key-here"]
    for file_path, content in staged_files_content.items():
        for key in discovered_api_keys:
            if (
                key and key in content and key not in placeholder_keys
            ):  # Ensure key is not empty
                print(
                    f"Error: Discovered API key found in staged file: {file_path}",
                    file=sys.stderr,
                )
                # Print a masked version of the key for safety, showing only start and end
                masked_key_snippet = (
                    f"'{key[:5]}...{key[-5:]}'" if len(key) > 10 else f"'{key}'"
                )
                print(f"  Key snippet: {masked_key_snippet}", file=sys.stderr)
                found_keys_in_staged_files = True
                break  # Found a key in this file, no need to check other keys or files
        if found_keys_in_staged_files:
            break

    if found_keys_in_staged_files:
        print("\nCommit aborted: Sensitive API keys detected in staged files.")
        print("Please remove the API keys from the staged files before committing.")
        sys.exit(1)
    else:
        print("No discovered API keys found in staged files. Proceeding with commit.")
        sys.exit(0)


if __name__ == "__main__":
    main()
