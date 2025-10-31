# Hybrid Backend Proof of Concept

This POC demonstrates the hybrid reasoning approach where we:
1. Capture reasoning output from a reasoning model (MiniMax-M2)
2. Augment the prompt with that reasoning
3. Send the augmented prompt to an execution model (GLM-4.6)

## Prerequisites

1. **Proxy server must be running** on `http://127.0.0.1:8000`
   ```bash
   python -m src.main
   ```

2. **Required models must be configured:**
   - `minimax:MiniMax-M2` (reasoning model)
   - `zai-coding-plan:glm-4.6` (execution model)

3. **Python dependencies:**
   - `httpx` (should already be installed)

## Usage

### Windows
```cmd
dev\run_hybrid_poc.bat "Your prompt here"
```

### Linux/Mac or Direct Python
```bash
python dev/hybrid_backend_poc.py "Your prompt here"
```

## Example

```bash
python dev/hybrid_backend_poc.py "Explain how neural networks learn through backpropagation"
```

## What to Expect

The script will display:

### Phase 1: Reasoning Model
- Connection details (model, proxy, prompt)
- Request payload
- **Streaming reasoning output** (in green)
- Detection of reasoning completion
- Stream cancellation confirmation
- Reasoning capture statistics

### Phase 2: Execution Model
- Connection details
- Augmented message structure (system message with reasoning)
- **Streaming execution output** (in green)
- Execution statistics

### Summary
- Total characters captured in each phase
- Success confirmation

## Output Format

The script uses color-coded output:
- **Cyan**: Phase 1 (Reasoning Model) headers
- **Blue**: Phase 2 (Execution Model) headers
- **Green**: Streaming content from models
- **Yellow**: Important events (reasoning detection, cancellation)
- **Red**: Errors
- **Purple**: Overall headers and summary

## Debugging

The script provides detailed debugging information:
- Request payloads (JSON)
- Response status codes
- Chunk counts
- Content lengths
- Reasoning detection triggers
- Stream cancellation confirmations

## Configuration

Edit `dev/hybrid_backend_poc.py` to change:
- `PROXY_BASE_URL`: Proxy server address (default: `http://127.0.0.1:8000/v1`)
- `REASONING_MODEL`: Model for reasoning phase (default: `minimax:MiniMax-M2`)
- `EXECUTION_MODEL`: Model for execution phase (default: `zai-coding-plan:glm-4.6`)
- `TIMEOUT`: Request timeout in seconds (default: 60.0)

## Reasoning Detection

The script detects reasoning completion by looking for:
1. `finish_reason` in response chunks (most reliable)
2. Content markers like `</think>`, `</reasoning>`, "therefore", "in conclusion"

You can adjust the detection logic in the `detect_reasoning_end()` function.

## Troubleshooting

### "Connection refused" error
- Ensure the proxy server is running on port 8000
- Check that you can access `http://127.0.0.1:8000/v1/models`

### "Model not found" error
- Verify the models are configured in your proxy
- Check model names match exactly (case-sensitive)

### No reasoning captured
- The reasoning model might not be producing reasoning output
- Try a different prompt that requires more reasoning
- Check if the model supports streaming

### Stream doesn't cancel
- The reasoning detection might not be triggering
- Check the `detect_reasoning_end()` function logic
- Try adjusting the detection markers

## Next Steps

After validating the POC:
1. Implement the full hybrid backend connector
2. Add CLI configuration support
3. Implement model capability detection
4. Add comprehensive error handling
5. Create unit and integration tests

## Notes

- This POC uses **system message injection** for reasoning augmentation
- The execution model receives reasoning in a `<thinking>` block
- Stream cancellation happens immediately after reasoning detection
- Both phases use streaming for real-time output visibility
