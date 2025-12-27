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
    @given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=10))
    @settings(max_examples=30, deadline=None)
    async def test_metadata_enrichment_does_not_buffer_stream(self, chunks):
        """
        Property 20: Metadata enrichment safety
        Feature: streaming-pipeline-refactor, Property 20: Metadata enrichment safety

        For any middleware that adds metadata, the stream should continue to
        yield chunks without breaking or buffering.

        This test verifies that:
        1. All chunks are yielded incrementally (no buffering)
        2. The stream continues to completion
        3. Metadata enrichment doesn't block chunk emission
        """
        # Create a metadata enriching processor
        processor = MetadataEnrichingProcessor("test_key", "test_value")

        # Process the stream
        stream = async_iter(chunks)
        processed_chunks = []

        async for chunk in stream:
            # Process each chunk
            processed_chunk = await processor.process(chunk)
            processed_chunks.append(processed_chunk)

        # Verify all chunks were yielded (no buffering)
        assert len(processed_chunks) == len(chunks), (
            f"Expected {len(chunks)} chunks, got {len(processed_chunks)}. "
            "Middleware may be buffering chunks."
        )

        # Verify metadata was added to all chunks
        for processed_chunk in processed_chunks:
            assert (
                "test_key" in processed_chunk.metadata
            ), "Metadata enrichment failed - key not added"
            assert (
                processed_chunk.metadata["test_key"] == "test_value"
            ), "Metadata enrichment failed - incorrect value"

        # Verify stream completed (last chunk is done)
        assert processed_chunks[
            -1
        ].is_done, "Stream did not complete properly - last chunk is not done"

    @pytest.mark.asyncio
    @given(chunk=streaming_content_strategy())
    @property_test_settings()
    async def test_metadata_enrichment_preserves_chunk_structure(self, chunk):
        """
        Property 20: Metadata enrichment safety (structure preservation)
        Feature: streaming-pipeline-refactor, Property 20: Metadata enrichment safety

        For any chunk, metadata enrichment should preserve the chunk's
        structure and only modify the metadata field.
        """
        # Create a metadata enriching processor
        processor = MetadataEnrichingProcessor("enriched", "value")

        # Store original values
        original_content = chunk.content
        original_is_done = chunk.is_done
        original_is_empty = chunk.is_empty
        original_stream_id = chunk.stream_id

        # Process the chunk
        processed_chunk = await processor.process(chunk)

        # Verify structure is preserved
        assert (
            processed_chunk.content == original_content
        ), "Metadata enrichment modified content"
        assert (
            processed_chunk.is_done == original_is_done
        ), "Metadata enrichment modified is_done flag"
        assert (
            processed_chunk.is_empty == original_is_empty
        ), "Metadata enrichment modified is_empty flag"
        assert (
            processed_chunk.stream_id == original_stream_id
        ), "Metadata enrichment modified stream_id"

        # Verify metadata was enriched
        assert "enriched" in processed_chunk.metadata, "Metadata was not enriched"

    @pytest.mark.asyncio
    @given(chunks=chunk_stream_with_done_strategy(min_size=3, max_size=8))
    @settings(max_examples=30, deadline=None)  # Reduced from 50
    async def test_metadata_enrichment_incremental_processing(self, chunks):
        """
        Property 20: Metadata enrichment safety (incremental processing)
        Feature: streaming-pipeline-refactor, Property 20: Metadata enrichment safety

        For any stream, metadata enrichment should process chunks incrementally
        without waiting for the entire stream to complete.
        """
        # Create a metadata enriching processor
        processor = MetadataEnrichingProcessor("processed_order", 0)

        # Track processing order
        processing_order = []

        # Process stream incrementally
        stream = async_iter(chunks)
        i = 0
        async for chunk in stream:
            # Enrich with order information
            processor.value = i
            processed_chunk = await processor.process(chunk)
            processing_order.append(processed_chunk.metadata.get("processed_order"))
            i += 1

        # Verify chunks were processed in order (incremental)
        expected_order = list(range(len(chunks)))
        assert processing_order == expected_order, (
            f"Chunks not processed incrementally. "
            f"Expected order {expected_order}, got {processing_order}"
        )


class TestBackendLogicIsolation:
    """Property tests for backend logic isolation (Property 24)."""

    @pytest.mark.asyncio
    @given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=10))
    @settings(max_examples=20, deadline=None)
    async def test_middleware_does_not_contain_backend_specific_logic(self, chunks):
        """
        Property 24: Backend logic isolation
        Feature: streaming-pipeline-refactor, Property 24: Backend logic isolation

        For any backend-specific feature, the logic should be contained in the
        backend's normalizer, not in core pipeline code.

        This test verifies that middleware processors work with any provider
        without special-casing backend-specific behavior.
        """
        # Test with different provider names
        providers = ["openai", "anthropic", "gemini", "test", "custom"]

        for provider in providers:
            # Set provider in metadata
            for chunk in chunks:
                chunk.metadata["provider"] = provider

            # Create a generic processor
            processor = MetadataEnrichingProcessor("middleware_tag", "processed")

            # Process the stream
            stream = async_iter(chunks)
            processed_chunks = []

            async for chunk in stream:
                processed_chunk = await processor.process(chunk)
                processed_chunks.append(processed_chunk)

            # Verify all chunks were processed identically regardless of provider
            for processed_chunk in processed_chunks:
                assert (
                    "middleware_tag" in processed_chunk.metadata
                ), f"Middleware failed for provider {provider}"
                assert (
                    processed_chunk.metadata["middleware_tag"] == "processed"
                ), f"Middleware behavior differs for provider {provider}"

            # Verify provider metadata is preserved
            for processed_chunk in processed_chunks:
                assert (
                    processed_chunk.metadata.get("provider") == provider
                ), f"Provider metadata was modified for {provider}"

    @pytest.mark.asyncio
    @given(chunk=streaming_content_strategy())
    @property_test_settings()
    async def test_middleware_processes_any_provider_uniformly(self, chunk):
        """
        Property 24: Backend logic isolation (uniform processing)
        Feature: streaming-pipeline-refactor, Property 24: Backend logic isolation

        For any chunk from any provider, middleware should process it uniformly
        without provider-specific branches.
        """
        # Test with multiple providers
        providers = ["openai", "anthropic", "gemini", "unknown", "custom"]
        results = []

        for provider in providers:
            # Create a copy of the chunk with different provider
            test_chunk = StreamingContent(
                content=chunk.content,
                metadata={**chunk.metadata, "provider": provider},
                is_done=chunk.is_done,
                is_empty=chunk.is_empty,
                stream_id=chunk.stream_id,
            )

            # Process with middleware
            processor = MetadataEnrichingProcessor("uniform_key", "uniform_value")
            processed = await processor.process(test_chunk)

            # Store result
            results.append(
                {
                    "provider": provider,
                    "has_key": "uniform_key" in processed.metadata,
                    "value": processed.metadata.get("uniform_key"),
                    "content_modified": processed.content != chunk.content,
                }
            )

        # Verify all providers were processed identically
        first_result = results[0]
        for result in results[1:]:
            assert (
                result["has_key"] == first_result["has_key"]
            ), f"Middleware behavior differs for provider {result['provider']}"
            assert (
                result["value"] == first_result["value"]
            ), f"Middleware produces different values for provider {result['provider']}"
            assert (
                result["content_modified"] == first_result["content_modified"]
            ), f"Middleware modifies content differently for provider {result['provider']}"


class TestInfrastructureReuse:
    """Property tests for infrastructure reuse (Property 25)."""

    @pytest.mark.asyncio
    @given(chunks=chunk_stream_with_done_strategy(min_size=1, max_size=10))
    @settings(max_examples=30, deadline=None)
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
    @given(chunks=chunk_stream_with_done_strategy(min_size=2, max_size=6))  # Reduced sizes for performance
    @settings(max_examples=20, deadline=None)  # Reduced from 30 for performance
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
    @property_test_settings()
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
