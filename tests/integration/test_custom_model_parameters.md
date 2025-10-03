# Plan for Testing Custom Model Parameters

This document outlines the plan to add integration tests for custom model parameters (`top_k` and `reasoning_effort`).

## 1. Create New Test File

A new test file will be created at `tests/integration/test_custom_model_parameters.py`.

## 2. Add `top_k` Integration Tests

The following tests will be added to verify that the `top_k` parameter is correctly passed to the backend connectors:

*   A test to confirm that `top_k` is included in the payload for the OpenRouter connector.
*   A test to confirm that `top_k` is included in the `generationConfig` for the Gemini connector.
*   A test to confirm that `top_k` is correctly ignored by the Anthropic connector, as expected.

## 3. Add `reasoning_effort` Integration Tests

The following tests will be added to verify that the `reasoning_effort` parameter is correctly passed to the backend connectors:

*   A test to confirm that `reasoning_effort` is included in the payload for the OpenRouter connector.
*   A test to confirm that `reasoning_effort` is correctly handled by the Gemini and Anthropic connectors.
