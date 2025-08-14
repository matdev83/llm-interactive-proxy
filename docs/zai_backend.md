# ZAI Backend Documentation

The ZAI backend is an OpenAI-compatible backend for Zhipu AI's GLM models. It extends the OpenAI connector and is configured to work with Zhipu AI's API endpoint.

## Configuration

To use the ZAI backend, you need to set the `ZAI_API_KEY` environment variable:

```bash
export ZAI_API_KEY="your-zai-api-key"
```

You can also use numbered API keys for rotation (similar to other backends):

```bash
export ZAI_API_KEY_1="your-first-zai-api-key"
export ZAI_API_KEY_2="your-second-zai-api-key"
```

## Usage

Once configured, you can use the ZAI backend by specifying it in your model name:

```python
# Using the ZAI backend with a specific model
response = openai.ChatCompletion.create(
    model="zai:glm-4.5-flash",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

Or set it as the default backend:

```bash
export LLM_BACKEND="zai"
```

## Supported Models

The ZAI backend supports the following models:
- `glm-4.5-flash`
- `glm-4.5-air` 
- `glm-4.5`

These are loaded from the configuration file `config/backends/zai/default_models.json` as fallback models in case the `/models` endpoint is not supported by the ZAI API.

### Customizing Default Models

If you need to update the list of default models, you can modify the `config/backends/zai/default_models.json` file:

```json
{
  "models": [
    "glm-4.5-flash",
    "glm-4.5-air",
    "glm-4.5",
    "glm-4.0"
  ],
  "description": "Default models for ZAI (Zhipu AI) backend",
  "last_updated": "2025-08-14"
}
```

## API Endpoint

The ZAI backend uses the following API endpoint:
`https://open.bigmodel.cn/api/paas/v4/`

This is the standard Zhipu AI API endpoint for their GLM models.