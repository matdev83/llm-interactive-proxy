This project is a versatile "swiss-army knife" proxy server designed to sit between LLM-aware clients and various LLM providers. It acts as a universal gateway, allowing you to route requests from any client to any backend provider.

Key capabilities include:
- **Universal Connectivity:** Presents multiple front-end APIs (OpenAI, Anthropic, Gemini) to support a wide range of clients, while routing requests to diverse backends including OpenAI, Anthropic (Claude), Google Gemini, OpenRouter, ZAI, Qwen, and custom providers.
- **Model Override:** Force applications to use specific models, overriding hardcoded defaults.
- **Safety & Security:** Features like dangerous command protection, file access sandboxing, and tool access control.
- **Angel Verification:** A real-time quality control system that uses a secondary LLM to verify and correct assistant responses before they reach the user.
- **Debugging:** Comprehensive wire capture and traffic inspection tools.