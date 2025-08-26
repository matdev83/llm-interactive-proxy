#!/usr/bin/env python3
"""
Test script for Gemini Cloud Project backend implementation.

This script tests the gemini-cli-cloud-project backend which requires:
1. A valid Google Cloud Project ID with billing enabled
2. Cloud AI Companion API enabled on the project
3. Valid OAuth credentials in ~/.gemini/oauth_creds.json
4. Appropriate IAM permissions (roles/cloudaicompanion.user)

Usage:
    python test_cloud_project.py --project YOUR_PROJECT_ID
    
    Or set environment variable:
    export GCP_PROJECT_ID=YOUR_PROJECT_ID
    python test_cloud_project.py
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from src.connectors.gemini_cloud_project import GeminiCloudProjectConnector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_initialization(project_id: str) -> GeminiCloudProjectConnector:
    """Test backend initialization with project ID."""
    logger.info(f"Testing initialization with project ID: {project_id}")
    
    client = httpx.AsyncClient()
    connector = GeminiCloudProjectConnector(
        client=client,
        gcp_project_id=project_id,
        credentials_path=Path.home() / ".gemini"  # Optional: specify path
    )
    
    try:
        await connector.initialize()
        
        if connector.is_functional:
            logger.info("✓ Backend initialized successfully")
            logger.info(f"  Available models: {len(connector.available_models)}")
            if connector.available_models:
                logger.info(f"  Sample models: {list(connector.available_models)[:3]}")
        else:
            logger.error("✗ Backend failed to initialize (not functional)")
            return None
            
    except Exception as e:
        logger.error(f"✗ Initialization failed: {e}")
        return None
    
    return connector


async def test_project_validation(connector: GeminiCloudProjectConnector) -> bool:
    """Test that project validation works correctly."""
    logger.info(f"Testing project validation for: {connector.gcp_project_id}")
    
    try:
        # This should have been done during initialization
        # but we can test it explicitly
        await connector._validate_project_access()
        logger.info("✓ Project validation successful")
        return True
    except Exception as e:
        logger.error(f"✗ Project validation failed: {e}")
        return False


async def test_chat_completion(connector: GeminiCloudProjectConnector) -> bool:
    """Test a simple chat completion."""
    logger.info("Testing chat completion...")
    
    # Create a simple request
    class MockRequest:
        temperature = 0.7
        max_tokens = 100
        stream = False
    
    messages = [
        {"role": "user", "content": "What is 2+2? Reply with just the number."}
    ]
    
    try:
        response = await connector.chat_completions(
            request_data=MockRequest(),
            processed_messages=messages,
            effective_model="gemini-1.5-flash-002"
        )
        
        if response and response.content:
            content = response.content
            if isinstance(content, dict):
                choices = content.get("choices", [])
                if choices:
                    answer = choices[0].get("message", {}).get("content", "")
                    logger.info(f"✓ Chat completion successful")
                    logger.info(f"  Response: {answer[:100]}...")
                    
                    # Check usage reporting (if available)
                    usage = content.get("usage", {})
                    if usage:
                        logger.info(f"  Token usage: {usage}")
                    return True
        
        logger.error("✗ Chat completion returned empty response")
        return False
        
    except Exception as e:
        logger.error(f"✗ Chat completion failed: {e}")
        return False


async def test_streaming_completion(connector: GeminiCloudProjectConnector) -> bool:
    """Test a streaming chat completion."""
    logger.info("Testing streaming chat completion...")
    
    # Create a streaming request
    class MockStreamRequest:
        temperature = 0.7
        max_tokens = 100
        stream = True
    
    messages = [
        {"role": "user", "content": "Count from 1 to 5 slowly."}
    ]
    
    try:
        response = await connector.chat_completions(
            request_data=MockStreamRequest(),
            processed_messages=messages,
            effective_model="gemini-1.5-flash-002"
        )
        
        if response and hasattr(response, 'content'):
            logger.info("✓ Streaming response created")
            
            # Collect stream chunks
            chunks = []
            async for chunk in response.content:
                if chunk:
                    chunks.append(chunk)
            
            if chunks:
                logger.info(f"  Received {len(chunks)} stream chunks")
                # Check if we got the [DONE] marker
                last_chunk = chunks[-1].decode() if chunks else ""
                if "[DONE]" in last_chunk:
                    logger.info("  Stream completed with [DONE] marker")
                return True
        
        logger.error("✗ Streaming completion returned empty response")
        return False
        
    except Exception as e:
        logger.error(f"✗ Streaming completion failed: {e}")
        return False


async def test_billing_project_context(connector: GeminiCloudProjectConnector) -> bool:
    """Test that requests are using the correct project for billing."""
    logger.info(f"Testing billing context for project: {connector.gcp_project_id}")
    
    # Make a request and verify it's using the right project
    class MockRequest:
        temperature = 0.5
        max_tokens = 50
        stream = False
    
    messages = [
        {"role": "user", "content": "Hello"}
    ]
    
    try:
        # The connector should be using the specified project ID
        if hasattr(connector, '_onboarded_project_id'):
            logger.info(f"✓ Using onboarded project: {connector._onboarded_project_id}")
            # It should match our input project
            if connector._onboarded_project_id == connector.gcp_project_id:
                logger.info("  Project ID matches expected value")
                return True
            else:
                logger.warning(f"  Project ID mismatch: expected {connector.gcp_project_id}, got {connector._onboarded_project_id}")
                return False
        else:
            # Make a request to trigger onboarding
            await connector.chat_completions(
                request_data=MockRequest(),
                processed_messages=messages,
                effective_model="gemini-1.5-flash-002"
            )
            
            if hasattr(connector, '_onboarded_project_id'):
                logger.info(f"✓ Successfully onboarded project: {connector._onboarded_project_id}")
                return True
                
    except Exception as e:
        logger.error(f"✗ Failed to verify billing project context: {e}")
        return False
    
    return False


async def main():
    """Main test function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Gemini Cloud Project backend")
    parser.add_argument(
        "--project",
        help="Google Cloud Project ID",
        default=os.getenv("GCP_PROJECT_ID")
    )
    parser.add_argument(
        "--credentials",
        help="Path to credentials directory",
        default=str(Path.home() / ".gemini")
    )
    args = parser.parse_args()
    
    if not args.project:
        logger.error("ERROR: No project ID provided. Use --project or set GCP_PROJECT_ID environment variable")
        logger.info("\nUsage:")
        logger.info("  python test_cloud_project.py --project YOUR_PROJECT_ID")
        logger.info("  OR")
        logger.info("  export GCP_PROJECT_ID=YOUR_PROJECT_ID")
        logger.info("  python test_cloud_project.py")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("Testing Gemini Cloud Project Backend")
    logger.info("=" * 60)
    logger.info(f"Project ID: {args.project}")
    logger.info(f"Credentials path: {args.credentials}")
    logger.info("")
    
    # Check if credentials exist
    creds_path = Path(args.credentials) / "oauth_creds.json"
    if not creds_path.exists():
        logger.error(f"ERROR: OAuth credentials not found at {creds_path}")
        logger.info("\nPlease run 'gemini auth' to authenticate first")
        sys.exit(1)
    
    logger.info(f"Found credentials at: {creds_path}")
    logger.info("")
    
    # Run tests
    client = httpx.AsyncClient()
    try:
        # Test 1: Initialization
        logger.info("-" * 40)
        connector = await test_initialization(args.project)
        if not connector:
            logger.error("Failed to initialize backend. Aborting tests.")
            return
        
        # Test 2: Project validation
        logger.info("-" * 40)
        validation_ok = await test_project_validation(connector)
        
        # Test 3: Chat completion
        logger.info("-" * 40)
        chat_ok = await test_chat_completion(connector)
        
        # Test 4: Streaming completion
        logger.info("-" * 40)
        stream_ok = await test_streaming_completion(connector)
        
        # Test 5: Billing context
        logger.info("-" * 40)
        billing_ok = await test_billing_project_context(connector)
        
        # Summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("TEST SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Initialization:    {'✓ PASS' if connector else '✗ FAIL'}")
        logger.info(f"Project validation: {'✓ PASS' if validation_ok else '✗ FAIL'}")
        logger.info(f"Chat completion:    {'✓ PASS' if chat_ok else '✗ FAIL'}")
        logger.info(f"Streaming:         {'✓ PASS' if stream_ok else '✗ FAIL'}")
        logger.info(f"Billing context:    {'✓ PASS' if billing_ok else '✗ FAIL'}")
        
        all_passed = all([connector, validation_ok, chat_ok, stream_ok, billing_ok])
        logger.info("")
        if all_passed:
            logger.info("✓ All tests passed! The backend is working correctly.")
            logger.info(f"  Your project '{args.project}' is properly configured for Gemini Code Assist.")
        else:
            logger.warning("⚠ Some tests failed. Please check the logs above for details.")
            logger.info("\nCommon issues:")
            logger.info("1. Ensure Cloud AI Companion API is enabled in your GCP project")
            logger.info("2. Ensure billing is enabled for your project")
            logger.info("3. Ensure you have the necessary IAM permissions")
            logger.info("4. Try running 'gemini auth' to refresh your credentials")
        
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
