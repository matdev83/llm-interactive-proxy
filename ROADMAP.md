# Project Roadmap

This document outlines planned work and longer term ideas for the proxy. Items are subject to change and are not guaranteed.

## Near term

- Improve error handling and logging around backend failures.
- Expand test coverage for the Gemini connector.
- Package and publish the project so it can be installed with `pip`.

## Future ideas

- Rate limiting and quota management using the `llm-accounting` service.
- Support additional LLM providers via new connectors.
- Automatic repair of responses containing diffs or file edits.
- More sophisticated session storage (database or Redis) for production use.

Contributions are welcome! Feel free to open issues or pull requests to discuss new features.

