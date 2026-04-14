from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from src.core.common.exceptions import (
    BackendError,
    RateLimitExceededError,
    RoutingError,
)
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.usage_window_warmup_config import (
    UsageWindowWarmupConfig,
    UsageWindowWarmupEntryConfig,
)
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.warmup_target_resolver_interface import IWarmupTargetResolver
from src.core.services.usage_window_warmup_service import UsageWindowWarmupService


def _entry(model: str, time: str) -> UsageWindowWarmupEntryConfig:
    return UsageWindowWarmupEntryConfig(model=model, time=time)


def _config(*entries: UsageWindowWarmupEntryConfig) -> UsageWindowWarmupConfig:
    return UsageWindowWarmupConfig(enabled=True, entries=list(entries))


class TestUsageWindowWarmupService:
    @pytest.mark.asyncio
    async def test_start_schedules_due_entries_and_stops_cleanly(self) -> None:
        completion_flow = AsyncMock()
        completion_flow.call_completion.return_value = ResponseEnvelope(
            content={"ok": True},
            status_code=200,
        )
        created_tasks: list[AsyncMock] = []
        fire_times: list[float] = []

        base_now = datetime(2026, 4, 11, 8, 0, 0)

        async def fake_sleep(delay: float) -> None:
            fire_times.append(delay)

        def fake_create_task(coro: object, name: str | None = None) -> object:
            del coro, name
            task = AsyncMock()
            created_tasks.append(task)
            return SimpleNamespace(done=lambda: False, cancel=lambda: None)

        service = UsageWindowWarmupService(
            completion_flow=completion_flow,
            config=_config(_entry(model="openai-codex:gpt-5.4-mini", time="08:00")),
            sleep_func=fake_sleep,
            random_delay_func=lambda: 7.0,
            random_number_func=lambda _min, _max: 111,
            now_provider=lambda: base_now,
            create_task_func=fake_create_task,
        )

        await service.start()
        await service.stop()

        assert service.is_running is False
        assert created_tasks
        assert fire_times == []

    @pytest.mark.asyncio
    async def test_execute_entry_retries_once_after_temporary_failure(self) -> None:
        completion_flow = AsyncMock()
        completion_flow.call_completion.side_effect = [
            TimeoutError("connection timed out"),
            ResponseEnvelope(content={"ok": True}, status_code=200),
        ]
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        service = UsageWindowWarmupService(
            completion_flow=completion_flow,
            config=_config(_entry(model="openai-codex:gpt-5.4-mini", time="08:00")),
            sleep_func=fake_sleep,
            random_delay_func=lambda: 5.0,
            random_number_func=lambda _min, _max: 123,
            now_provider=lambda: datetime(2026, 4, 11, 8, 0, 0),
        )

        await service._execute_entry(
            _entry(model="openai-codex:gpt-5.4-mini", time="08:00")
        )

        # Should retry once after timeout and then succeed
        assert completion_flow.call_completion.await_count == 2
        assert sleep_calls == [5.0]

    @pytest.mark.asyncio
    async def test_execute_entry_builds_expected_prompt_and_context(self) -> None:
        completion_flow = AsyncMock()
        completion_flow.call_completion.return_value = ResponseEnvelope(
            content={"ok": True},
            status_code=200,
        )

        service = UsageWindowWarmupService(
            completion_flow=completion_flow,
            config=_config(
                _entry(model="gemini.2:google/gemini-2.5-flash", time="13:30")
            ),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 9.0,
            random_number_func=lambda _min, _max: 4321,
            now_provider=lambda: datetime(2026, 4, 11, 13, 30, 0),
        )

        await service._execute_entry(
            _entry(model="gemini.2:google/gemini-2.5-flash", time="13:30")
        )

        request = completion_flow.call_completion.await_args.args[0]
        context = completion_flow.call_completion.await_args.kwargs["context"]
        assert request.model == "gemini.2:google/gemini-2.5-flash"
        assert isinstance(request.messages[0], ChatMessage)
        assert (
            request.messages[0].content
            == "Hi, how much is it 4321 times 4321 plus 4321"
        )
        assert context.session_id is not None
        assert context.request_id is not None
        assert context.agent == "usage-window-warmup"

    @pytest.mark.asyncio
    async def test_execute_entry_fans_out_openai_codex_across_accounts(self) -> None:
        completion_flow = AsyncMock()
        completion_flow.call_completion.return_value = ResponseEnvelope(
            content={"ok": True},
            status_code=200,
        )

        class _Resolver(IWarmupTargetResolver):
            async def resolve_target_accounts(self, backend_type: str) -> list[str]:
                if backend_type == "openai-codex":
                    return ["acct_a", "acct_b"]
                return []

        service = UsageWindowWarmupService(
            completion_flow=completion_flow,
            config=_config(_entry(model="openai-codex:gpt-5.4-mini", time="13:30")),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 0.0,
            random_number_func=lambda _min, _max: 4321,
            now_provider=lambda: datetime(2026, 4, 11, 13, 30, 0),
            target_resolver=_Resolver(),
        )

        await service._execute_entry(
            _entry(model="openai-codex:gpt-5.4-mini", time="13:30")
        )

        assert completion_flow.call_completion.await_count == 2
        seen_accounts: set[str] = set()
        for call in completion_flow.call_completion.await_args_list:
            request = call.args[0]
            context = call.kwargs["context"]
            assert request.extra_body is not None
            account_id = request.extra_body.get("openai_codex_managed_account_id")
            assert isinstance(account_id, str)
            seen_accounts.add(account_id)
            assert (
                context.extensions.get("openai_codex_managed_account_id") == account_id
            )
            assert context.extensions.get("warmup_target_account_id") == account_id
        assert seen_accounts == {"acct_a", "acct_b"}

    @pytest.mark.asyncio
    async def test_execute_entry_non_codex_keeps_single_request(self) -> None:
        completion_flow = AsyncMock()
        completion_flow.call_completion.return_value = ResponseEnvelope(
            content={"ok": True},
            status_code=200,
        )

        class _Resolver(IWarmupTargetResolver):
            async def resolve_target_accounts(self, backend_type: str) -> list[str]:
                return ["acct_a", "acct_b"]

        service = UsageWindowWarmupService(
            completion_flow=completion_flow,
            config=_config(
                _entry(model="gemini.2:google/gemini-2.5-flash", time="13:30")
            ),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 0.0,
            random_number_func=lambda _min, _max: 4321,
            now_provider=lambda: datetime(2026, 4, 11, 13, 30, 0),
            target_resolver=_Resolver(),
        )

        await service._execute_entry(
            _entry(model="gemini.2:google/gemini-2.5-flash", time="13:30")
        )

        assert completion_flow.call_completion.await_count == 1
        request = completion_flow.call_completion.await_args.args[0]
        assert request.extra_body is None

    def test_compute_delay_until_next_run_rolls_to_next_business_day(self) -> None:
        service = UsageWindowWarmupService(
            completion_flow=AsyncMock(),
            config=_config(_entry(model="openai-codex:gpt-5.4-mini", time="08:00")),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 5.0,
            random_number_func=lambda _min, _max: 123,
            now_provider=lambda: datetime(2026, 4, 11, 8, 0, 1),
        )

        delay = service._compute_delay_until_next_run(
            _entry(model="openai-codex:gpt-5.4-mini", time="08:00"),
            datetime(2026, 4, 11, 8, 0, 1),
        )

        assert delay == pytest.approx(
            timedelta(days=1, hours=23, minutes=59, seconds=59).total_seconds()
        )

    def test_compute_delay_skips_weekend_when_entry_disables_weekends(self) -> None:
        service = UsageWindowWarmupService(
            completion_flow=AsyncMock(),
            config=UsageWindowWarmupConfig(
                enabled=True,
                entries=[
                    UsageWindowWarmupEntryConfig(
                        model="openai-codex:gpt-5.4-mini",
                        time="08:00",
                    )
                ],
            ),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 5.0,
            random_number_func=lambda _min, _max: 123,
            now_provider=lambda: datetime(2026, 4, 11, 7, 59, 0),
        )

        delay = service._compute_delay_until_next_run(
            UsageWindowWarmupEntryConfig(
                model="openai-codex:gpt-5.4-mini",
                time="08:00",
            ),
            datetime(2026, 4, 11, 7, 59, 0),
        )

        assert delay == pytest.approx(timedelta(days=2, minutes=1).total_seconds())

    def test_compute_delay_keeps_weekend_run_when_entry_allows_it(self) -> None:
        service = UsageWindowWarmupService(
            completion_flow=AsyncMock(),
            config=UsageWindowWarmupConfig(
                enabled=True,
                entries=[
                    UsageWindowWarmupEntryConfig(
                        model="openai-codex:gpt-5.4-mini",
                        time="08:00",
                        execute_on_weekend=True,
                    )
                ],
            ),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 5.0,
            random_number_func=lambda _min, _max: 123,
            now_provider=lambda: datetime(2026, 4, 11, 7, 59, 0),
        )

        delay = service._compute_delay_until_next_run(
            UsageWindowWarmupEntryConfig(
                model="openai-codex:gpt-5.4-mini",
                time="08:00",
                execute_on_weekend=True,
            ),
            datetime(2026, 4, 11, 7, 59, 0),
        )

        assert delay == pytest.approx(timedelta(minutes=1).total_seconds())

    @pytest.mark.asyncio
    async def test_execute_entry_does_not_retry_on_permanent_errors(self) -> None:
        completion_flow = AsyncMock()
        completion_flow.call_completion.side_effect = RoutingError(
            message="Permanent routing error"
        )

        service = UsageWindowWarmupService(
            completion_flow=completion_flow,
            config=_config(_entry(model="openai-codex:gpt-5.4-mini", time="08:00")),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 5.0,
            random_number_func=lambda _min, _max: 123,
            now_provider=lambda: datetime(2026, 4, 11, 8, 0, 0),
        )

        await service._execute_entry(
            _entry(model="openai-codex:gpt-5.4-mini", time="08:00")
        )

        # Should only try once for permanent routing errors
        assert completion_flow.call_completion.await_count == 1

    @pytest.mark.asyncio
    async def test_execute_entry_does_not_retry_4xx_errors(self) -> None:
        completion_flow = AsyncMock()
        completion_flow.call_completion.side_effect = BackendError(
            message="Bad request",
            status_code=400,
            details={"model": "test"},
        )

        service = UsageWindowWarmupService(
            completion_flow=completion_flow,
            config=_config(_entry(model="openai-codex:gpt-5.4-mini", time="08:00")),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 5.0,
            random_number_func=lambda _min, _max: 123,
            now_provider=lambda: datetime(2026, 4, 11, 8, 0, 0),
        )

        await service._execute_entry(
            _entry(model="openai-codex:gpt-5.4-mini", time="08:00")
        )

        # Should only try once for 4xx client errors
        assert completion_flow.call_completion.await_count == 1

    @pytest.mark.asyncio
    async def test_execute_entry_retries_5xx_errors_once(self) -> None:
        completion_flow = AsyncMock()
        completion_flow.call_completion.side_effect = [
            BackendError(
                message="Server error",
                status_code=500,
                details={"model": "test"},
            ),
            ResponseEnvelope(content={"ok": True}, status_code=200),
        ]

        service = UsageWindowWarmupService(
            completion_flow=completion_flow,
            config=_config(_entry(model="openai-codex:gpt-5.4-mini", time="08:00")),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 5.0,
            random_number_func=lambda _min, _max: 123,
            now_provider=lambda: datetime(2026, 4, 11, 8, 0, 0),
        )

        await service._execute_entry(
            _entry(model="openai-codex:gpt-5.4-mini", time="08:00")
        )

        # Should retry once for 5xx server errors and then succeed
        assert completion_flow.call_completion.await_count == 2

    @pytest.mark.asyncio
    async def test_execute_entry_retries_429_errors_once(self) -> None:
        completion_flow = AsyncMock()
        completion_flow.call_completion.side_effect = [
            BackendError(
                message="Rate limited",
                status_code=429,
                details={"model": "test"},
            ),
            ResponseEnvelope(content={"ok": True}, status_code=200),
        ]

        service = UsageWindowWarmupService(
            completion_flow=completion_flow,
            config=_config(_entry(model="openai-codex:gpt-5.4-mini", time="08:00")),
            sleep_func=AsyncMock(),
            random_delay_func=lambda: 5.0,
            random_number_func=lambda _min, _max: 123,
            now_provider=lambda: datetime(2026, 4, 11, 8, 0, 0),
        )

        await service._execute_entry(
            _entry(model="openai-codex:gpt-5.4-mini", time="08:00")
        )

        # Should retry once for 429 rate limit errors and then succeed
        assert completion_flow.call_completion.await_count == 2

    def test_is_retryable_error_classifies_errors_correctly(self) -> None:
        from src.core.common.exceptions import BackendError, LLMProxyError

        # Permanent errors - should NOT retry
        assert (
            UsageWindowWarmupService._is_retryable_error(RoutingError("test")) is False
        )
        assert (
            UsageWindowWarmupService._is_retryable_error(
                BackendError("test", status_code=400)
            )
            is False
        )
        assert (
            UsageWindowWarmupService._is_retryable_error(
                BackendError("test", status_code=404)
            )
            is False
        )
        # Note: BackendError without explicit status_code defaults to 502,
        # which is >= 500 and thus retryable. This is the intended behavior -
        # backend errors without specific status codes are treated as server errors.

        # Temporary errors - SHOULD retry
        assert (
            UsageWindowWarmupService._is_retryable_error(TimeoutError("timeout"))
            is True
        )
        assert (
            UsageWindowWarmupService._is_retryable_error(
                ConnectionError("connection failed")
            )
            is True
        )
        assert (
            UsageWindowWarmupService._is_retryable_error(
                BackendError("test", status_code=500)
            )
            is True
        )
        assert (
            UsageWindowWarmupService._is_retryable_error(
                BackendError("test", status_code=503)
            )
            is True
        )
        assert (
            UsageWindowWarmupService._is_retryable_error(
                BackendError("test", status_code=429)
            )
            is True
        )
        assert (
            UsageWindowWarmupService._is_retryable_error(
                RateLimitExceededError("Rate limit reached for requests")
            )
            is True
        )

        # LLMProxyError with retryable flag
        assert (
            UsageWindowWarmupService._is_retryable_error(
                LLMProxyError("test", details={"retryable": True})
            )
            is True
        )
        assert (
            UsageWindowWarmupService._is_retryable_error(
                LLMProxyError("test", details={"retryable": False})
            )
            is False
        )

        # Unknown error types - assume permanent
        assert (
            UsageWindowWarmupService._is_retryable_error(ValueError("unknown error"))
            is False
        )
