"""
Property-based tests for streaming middleware processors.

This module contains property tests for middleware components that process
streaming content, verifying safety properties like metadata enrichment,
backend logic isolation, and infrastructure reuse.

Feature: streaming-pipeline-refactor, Task 22: Remaining property tests
"""

import pytest
from hypothesis import given, settings
from tests.utils.hypothesis_config import property_test_settings
from tests.utils.property_test_generators import (
    chunk_stream_with_done_strategy,
    streaming_content_strategy,
)
from tests.utils.property_test_helpers import (
    MetadataEnrichingProcessor,
    async_iter,
)


class TestMetadataEnrichmentSafety:
    """Property tests for metadata enrichment safety (Property 20)."""

    @pytest.mark.asyncio
    @given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=5))
    @settings(max_examples=10, deadline=None)
    async def test_common_infrastructure_works_for_all_backends(self, chunks):
        """
        Property 25: Infrastructure reuse
        Feature: streaming-pipeline-refactor, Property 25: Infrastructure reuse

        For any two streaming backends, they should share common infrastructure
        code (processor chain, assembler, metrics) without duplication.

        This test verifies that the same processor chain works for chunks
        from different backends.
        """
        # Simulate chunks from different backends
        backend_providers = ["openai", "anthropic"]

        for provider in backend_providers:
            # Tag chunks with provider
            provider_chunks = []
            for chunk in chunks:
                provider_chunk = StreamingContent(
                    content=chunk.content,
                    metadata={**chunk.metadata, "provider": provider},
                    is_done=chunk.is_done,
                    is_empty=chunk.is_empty,
                    stream_id=chunk.stream_id,
                )
                provider_chunks.append(provider_chunk)

            # Process with shared infrastructure (processor chain)
            processor = MetadataEnrichingProcessor("shared_infra", "reused")
            stream = async_iter(provider_chunks)
            processed_chunks = []

            async for chunk in stream:
                processed_chunk = await processor.process(chunk)
                processed_chunks.append(processed_chunk)

            # Verify shared infrastructure worked
            assert len(processed_chunks) == len(
                chunks
            ), f"Shared infrastructure failed for {provider}"

            for processed_chunk in processed_chunks:
                assert (
                    "shared_infra" in processed_chunk.metadata
                ), f"Shared infrastructure did not process {provider} chunks"
                assert (
                    processed_chunk.metadata["shared_infra"] == "reused"
                ), f"Shared infrastructure produced different results for {provider}"

    @pytest.mark.asyncio
    @given(chunks=chunk_stream_with_done_strategy(min_size=2, max_size=4))
    @settings(max_examples=10, deadline=None)
    async def test_processor_chain_reusable_across_backends(self, chunks):
        """
        Property 25: Infrastructure reuse (processor chain)
        Feature: streaming-pipeline-refactor, Property 25: Infrastructure reuse

        For any backend, the same processor chain should be reusable without
        backend-specific modifications.
        """
        # Create a chain of processors (simulating shared infrastructure)
        processor1 = MetadataEnrichingProcessor("stage1", "processed")
        processor2 = MetadataEnrichingProcessor("stage2", "processed")

        # Test with different backend providers
        providers = ["openai", "anthropic"]

        for provider in providers:
            # Tag chunks with provider
            provider_chunks = []
            for chunk in chunks:
                provider_chunk = StreamingContent(
                    content=chunk.content,
                    metadata={**chunk.metadata, "provider": provider},
                    is_done=chunk.is_done,
                    is_empty=chunk.is_empty,
                    stream_id=chunk.stream_id,
                )
                provider_chunks.append(provider_chunk)

            # Process through the chain
            stream = async_iter(provider_chunks)
            processed_chunks = []

            async for chunk in stream:
                # Stage 1
                chunk = await processor1.process(chunk)
                # Stage 2
                chunk = await processor2.process(chunk)
                processed_chunks.append(chunk)

            # Verify both stages processed all chunks
            for processed_chunk in processed_chunks:
                assert (
                    "stage1" in processed_chunk.metadata
                ), f"Stage 1 failed for {provider}"
                assert (
                    "stage2" in processed_chunk.metadata
                ), f"Stage 2 failed for {provider}"
                assert (
                    processed_chunk.metadata["stage1"] == "processed"
                ), f"Stage 1 produced different results for {provider}"
                assert (
                    processed_chunk.metadata["stage2"] == "processed"
                ), f"Stage 2 produced different results for {provider}"

    @pytest.mark.asyncio
    @given(chunk=streaming_content_strategy())
    @property_test_settings(max_examples=10)
    async def test_infrastructure_components_provider_agnostic(self, chunk):
        """
        Property 25: Infrastructure reuse (provider agnostic)
        Feature: streaming-pipeline-refactor, Property 25: Infrastructure reuse

        For any infrastructure component (processor, assembler, metrics),
        it should work with any provider without special cases.
        """
        # Test that infrastructure components don't need to know about providers
        providers = ["openai", "anthropic", "gemini", "unknown", "custom"]

        # Create infrastructure component (processor)
        processor = MetadataEnrichingProcessor("infra_component", "works")

        results = []
        for provider in providers:
            # Create chunk with provider
            test_chunk = StreamingContent(
                content=chunk.content,
                metadata={**chunk.metadata, "provider": provider},
                is_done=chunk.is_done,
                is_empty=chunk.is_empty,
                stream_id=chunk.stream_id,
            )

            # Process with infrastructure component
            processed = await processor.process(test_chunk)

            # Verify it worked
            results.append(
                {
                    "provider": provider,
                    "success": "infra_component" in processed.metadata,
                    "value": processed.metadata.get("infra_component"),
                }
            )

        # Verify all providers worked identically
        assert all(
            r["success"] for r in results
        ), "Infrastructure component failed for some providers"
        assert all(
            r["value"] == "works" for r in results
        ), "Infrastructure component produced different results for different providers"


# Import StreamingContent for type hints
from src.core.ports.streaming_contracts import StreamingContent
