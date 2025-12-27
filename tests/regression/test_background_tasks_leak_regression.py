"""Regression test for AppLifecycle and ResponseProcessor background tasks memory leak fix.

This test verifies that completed background tasks are properly cleaned up
and don't accumulate in AppLifecycle and ResponseProcessor.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from src.core.app.lifecycle import AppLifecycle
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from tests.utils.fake_clock import FakeClockContext


class TestBackgroundTasksLeakRegression:
    """Regression tests for background tasks memory leak fix."""

    @pytest.mark.asyncio
    async def test_app_lifecycle_background_tasks_cleaned_up(self) -> None:
        """Test that completed background tasks are cleaned up in AppLifecycle."""
        app = FastAPI()
        lifecycle = AppLifecycle(app, {})

        initial_count = len(lifecycle._background_tasks)

        # Create and complete many tasks
        num_tasks = 100
        for i in range(num_tasks):

            async def dummy_task(task_id: int = i):
                return task_id

            task = asyncio.create_task(dummy_task())
            lifecycle._background_tasks.append(task)
            task.add_done_callback(lifecycle._remove_completed_task)

        # Wait for all tasks to complete
        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.01))
            clock.advance(0.01)
            await sleep_task

        # Check if tasks are cleaned up
        final_count = len(lifecycle._background_tasks)

        # Allow some margin for tasks that haven't completed yet
        # But should be much less than num_tasks
        assert final_count <= initial_count + 10, (
            f"Background tasks not cleaned up properly. "
            f"Initial: {initial_count}, Final: {final_count}, Expected: ~{initial_count}. "
            f"{final_count - initial_count} completed tasks accumulated."
        )

    @pytest.mark.asyncio
    async def test_response_processor_background_tasks_cleaned_up(self) -> None:
        """Test that completed background tasks are cleaned up in ResponseProcessor."""
        # Create ResponseProcessor with mocked dependencies
        mock_parser = MagicMock(spec=IResponseParser)
        mock_parser.parse_response.return_value = {}
        mock_parser.extract_content.return_value = ""
        mock_parser.extract_usage.return_value = {}
        mock_parser.extract_metadata.return_value = {}

        stream_normalizer = StreamNormalizer(processors=[])
        processor = ResponseProcessor(
            response_parser=mock_parser,  # type: ignore[type-abstract]
            stream_normalizer=stream_normalizer,
        )

        initial_count = len(processor._background_tasks)

        # Create and complete many tasks
        num_tasks = 100
        for i in range(num_tasks):

            async def dummy_task(task_id: int = i):
                return task_id

            task = asyncio.create_task(dummy_task())
            processor.add_background_task(task)

        # Wait for all tasks to complete
        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.01))
            clock.advance(0.01)
            await sleep_task

        # Check if tasks are cleaned up
        final_count = len(processor._background_tasks)

        # Allow some margin for tasks that haven't completed yet
        # But should be much less than num_tasks
        assert final_count <= initial_count + 10, (
            f"Background tasks not cleaned up properly. "
            f"Initial: {initial_count}, Final: {final_count}, Expected: ~{initial_count}. "
            f"{final_count - initial_count} completed tasks accumulated."
        )
