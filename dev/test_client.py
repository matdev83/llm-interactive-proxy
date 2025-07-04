import argparse
import json
import logging
import os
from typing import List, Dict, Any

import openai

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')


def validate_output_filename(filename: str) -> str:
    if os.path.sep in filename or (os.path.altsep and os.path.altsep in filename):
        raise ValueError("Output filename must not contain path separators")
    if not filename.endswith('.txt'):
        raise ValueError("Output filename must end with .txt")
    return os.path.join(OUTPUT_DIR, filename)


def load_config(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def _prepare_messages_for_prompt(prm: Any) -> List[Dict[str, Any]]:
    """Prepares the 'messages' list for the OpenAI API call based on the prompt type."""
    if isinstance(prm, dict):
        if 'role' not in prm or 'content' not in prm:
            raise ValueError('Prompt dict must contain role and content fields.')
        # Ensure content is string if it's a simple role/content dict for user/assistant
        # This doesn't try to handle complex multimodal content structures here,
        # assuming the input `prm` dict is already correctly formatted if it's complex.
        if not isinstance(prm['content'], (str, list)): # Allow list for multimodal
             prm['content'] = str(prm['content'])
        return [prm]
    else: # Assume it's a simple string prompt
        return [{'role': 'user', 'content': str(prm)}]

def _extract_content_from_response(resp: Any) -> str:
    """Extracts content from various possible OpenAI/OpenRouter response structures."""
    content = None
    # Standard OpenAI response structure
    if hasattr(resp, "choices") and resp.choices:
        message = resp.choices[0].message
        if hasattr(message, "content"):
            content = message.content
    # Gemini-like structure (often seen via OpenRouter)
    elif hasattr(resp, "candidates") and resp.candidates:
        candidate = resp.candidates[0]
        if hasattr(candidate, "content") and hasattr(candidate.content, "parts") and candidate.content.parts:
            content = "".join(part.text for part in candidate.content.parts if hasattr(part, "text"))
        # Fallback for slightly different Gemini structures sometimes seen
        elif hasattr(candidate, "text"): # pragma: no cover
             content = candidate.text

    if content is None: # If no specific structure matched, convert the whole response to string
        logger.warning(f"Could not extract content using known structures, falling back to str(resp). Response type: {type(resp)}")
        content = str(resp)

    # Ensure content is a string, not None or other types before returning
    return str(content) if content is not None else ""


def run_prompts(client: openai.OpenAI, model: str, prompts: List[Any]) -> List[str]:
    results = []
    for prm in prompts:
        try:
            messages = _prepare_messages_for_prompt(prm)
            resp = client.chat.completions.create(model=model, messages=messages)
            extracted_content = _extract_content_from_response(resp)
            results.append(extracted_content)
        except Exception as e:
            logger.error(f"Error processing prompt '{str(prm)[:50]}...': {e}", exc_info=True)
            results.append(f"ERROR: {e}") # Append error message to results
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
