import argparse
import json
import logging
import os
from typing import Any

import openai

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')


def validate_output_filename(filename: str) -> str:
    if os.path.sep in filename or (os.path.altsep and os.path.altsep in filename):
        raise ValueError("Output filename must not contain path separators")
    if not filename.endswith('.txt'):
        raise ValueError("Output filename must end with .txt")
    return os.path.join(OUTPUT_DIR, filename)


def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def run_prompts(client: openai.OpenAI, model: str, prompts: list[Any]) -> list[str]:
    results = []
    for prm in prompts:
        if isinstance(prm, dict):
            messages = [prm]
            if 'role' not in prm or 'content' not in prm:
                raise ValueError('Prompt dict must contain role and content')
        else:
            messages = [{'role': 'user', 'content': str(prm)}]
        resp = client.chat.completions.create(model=model, messages=messages)
        content = None
        if getattr(resp, "choices", None):
            content = resp.choices[0].message.content
        elif getattr(resp, "candidates", None):
            cand = resp.candidates[0]
            parts = cand.get("content", {}).get("parts") if isinstance(cand, dict) else getattr(cand, "content", {}).get("parts")
            if parts:
                content = "".join(p.get("text", "") if isinstance(p, dict) else getattr(p, "text", "") for p in parts)
        if content is None:
            content = str(resp)
        results.append(content)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple test client for proxy")
    parser.add_argument('config', help='JSON configuration file')
    parser.add_argument('-o', '--output', help='Output filename (stored under dev/output)')
    args = parser.parse_args()

    config = load_config(args.config)
    api_key = config.get('api_key') or os.environ.get('OPENAI_API_KEY')
    api_base = config.get('api_base')
    model = config.get('model', 'gpt-3.5-turbo')
    prompts = config.get('prompts', [])

    client = openai.OpenAI(api_key=api_key, base_url=api_base)

    logging.basicConfig(level=logging.INFO)

    results = run_prompts(client, model, prompts)

    if args.output:
        out_path = validate_output_filename(args.output)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            for line in results:
                f.write(line + '\n')
    else:
        for line in results:
            logger.info(line)


if __name__ == '__main__':
    main()
