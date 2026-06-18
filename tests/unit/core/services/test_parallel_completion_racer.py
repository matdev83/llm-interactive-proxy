from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import pytest
from src.core.common.exceptions import RoutingError
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.parallel_completion_racer import (
    ParallelCompletionRacer,
    ParallelRaceLeg,
)

from tests.utils.fake_clock import FakeClock, FakeClockContext


def _ready_event() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


@dataclass
class _TrackedLeg:
    leg_id: str
    chunks: list[bytes]
    release_first_token: asyncio.Event = field(default_factory=asyncio.Event)
    release_rest: asyncio.Event = field(default_factory=_ready_event)
    started: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_calls: int = 0

    async def stream_factory(self) -> AsyncIterator[bytes]:
        self.started.set()
        await self.release_first_token.wait()
        if self.cancelled.is_set():
            return
        for chunk in self.chunks:
            if self.cancelled.is_set():
                return
            yield chunk
            if len(self.chunks) > 1:
                await self.release_rest.wait()

    async def cancel(self) -> None:
        self.cancel_calls += 1
        self.cancelled.set()

    def to_race_leg(
        self,
        *,
        handicap_seconds: float = 0.0,
        ttft_timeout_seconds: float = 0.0,
    ) -> ParallelRaceLeg:
        return ParallelRaceLeg(
            leg_id=self.leg_id,
            stream_factory=self.stream_factory,
            handicap_seconds=handicap_seconds,
            ttft_timeout_seconds=ttft_timeout_seconds,
            cancel=self.cancel,
        )


@dataclass
class _FlakyCancelLeg(_TrackedLeg):
    fail_cancel_once: bool = True

    async def cancel(self) -> None:
        self.cancel_calls += 1
        if self.fail_cancel_once:
            self.fail_cancel_once = False
            raise RuntimeError("cancel failed")
        self.cancelled.set()


async def _collect_race_output(
    racer: ParallelCompletionRacer,
    legs: list[ParallelRaceLeg],
    *,
    client_cancelled: asyncio.Event | None = None,
    keepalive_factory: Callable[[], bytes] | None = None,
) -> tuple[list[bytes], str | None]:
    output: list[bytes] = []
    winning_leg_id: str | None = None
    async for chunk, winner in racer.race(
        legs,
        client_cancelled=client_cancelled,
        keepalive_factory=keepalive_factory,
        keepalive_interval_seconds=5.0,
    ):
        output.append(chunk)
        if winner is not None:
            winning_leg_id = winner
    return output, winning_leg_id


@pytest.mark.asyncio
async def test_parallel_racer_first_token_wins_and_cancels_losers() -> None:
    leg_a = _TrackedLeg(leg_id="a", chunks=[b"a-token", b"a-rest"])
    leg_b = _TrackedLeg(leg_id="b", chunks=[b"b-token", b"b-rest"])
    racer = ParallelCompletionRacer()

    race_task = asyncio.create_task(
        _collect_race_output(
            racer,
            [leg_a.to_race_leg(), leg_b.to_race_leg()],
        )
    )
    await asyncio.wait_for(leg_a.started.wait(), timeout=1.0)
    await asyncio.wait_for(leg_b.started.wait(), timeout=1.0)

    leg_b.release_first_token.set()
    output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "b"
    assert output == [b"b-token", b"b-rest"]
    assert leg_a.cancel_calls == 1
    assert leg_b.cancel_calls == 0


@pytest.mark.asyncio
async def test_parallel_racer_max_handicap_starts_immediately() -> None:
    leg_high = _TrackedLeg(leg_id="high", chunks=[b"high-token"])
    leg_low = _TrackedLeg(leg_id="low", chunks=[b"low-token"])
    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    leg_high.to_race_leg(handicap_seconds=10.0),
                    leg_low.to_race_leg(handicap_seconds=0.0),
                ],
            )
        )
        await asyncio.wait_for(leg_high.started.wait(), timeout=1.0)
        assert leg_low.started.is_set() is False
        assert clock.now() == pytest.approx(1000.0)

        leg_high.release_first_token.set()
        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "high"
    assert output == [b"high-token"]
    assert leg_low.cancel_calls == 1
    assert leg_low.started.is_set() is False


@pytest.mark.asyncio
async def test_parallel_racer_lower_handicap_delayed_by_max_minus_handicap() -> None:
    leg_10 = _TrackedLeg(leg_id="h10", chunks=[b"t10"])
    leg_5 = _TrackedLeg(leg_id="h5", chunks=[b"t5"])
    leg_2 = _TrackedLeg(leg_id="h2", chunks=[b"t2"])
    leg_0 = _TrackedLeg(leg_id="h0", chunks=[b"t0"])
    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    leg_10.to_race_leg(handicap_seconds=10.0),
                    leg_5.to_race_leg(handicap_seconds=5.0),
                    leg_2.to_race_leg(handicap_seconds=2.0),
                    leg_0.to_race_leg(handicap_seconds=0.0),
                ],
            )
        )

        await asyncio.wait_for(leg_10.started.wait(), timeout=1.0)
        assert clock.now() == pytest.approx(1000.0)
        assert leg_5.started.is_set() is False
        assert leg_2.started.is_set() is False
        assert leg_0.started.is_set() is False

        clock.advance(5.0)
        await asyncio.sleep(0)
        await asyncio.wait_for(leg_5.started.wait(), timeout=1.0)
        assert clock.now() == pytest.approx(1005.0)
        assert leg_2.started.is_set() is False
        assert leg_0.started.is_set() is False

        clock.advance(3.0)
        await asyncio.sleep(0)
        await asyncio.wait_for(leg_2.started.wait(), timeout=1.0)
        assert clock.now() == pytest.approx(1008.0)
        assert leg_0.started.is_set() is False

        clock.advance(2.0)
        await asyncio.sleep(0)
        await asyncio.wait_for(leg_0.started.wait(), timeout=1.0)
        assert clock.now() == pytest.approx(1010.0)

        leg_10.release_first_token.set()
        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "h10"
    assert output == [b"t10"]
    assert leg_5.cancel_calls == 1
    assert leg_2.cancel_calls == 1
    assert leg_0.cancel_calls == 1


@pytest.mark.asyncio
async def test_parallel_racer_early_winner_prevents_later_scheduled_starts() -> None:
    leg_high = _TrackedLeg(leg_id="high", chunks=[b"high-token"])
    leg_low = _TrackedLeg(leg_id="low", chunks=[b"low-token"])
    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    leg_high.to_race_leg(handicap_seconds=10.0),
                    leg_low.to_race_leg(handicap_seconds=0.0),
                ],
            )
        )
        await asyncio.wait_for(leg_high.started.wait(), timeout=1.0)
        assert leg_low.started.is_set() is False

        leg_high.release_first_token.set()
        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

        clock.advance(10.0)
        await asyncio.sleep(0)

    assert winner == "high"
    assert output == [b"high-token"]
    assert leg_low.cancel_calls == 1
    assert leg_low.started.is_set() is False


@pytest.mark.asyncio
async def test_parallel_racer_equal_handicap_legs_start_concurrently() -> None:
    leg_anchor = _TrackedLeg(leg_id="anchor", chunks=[b"anchor-token"])
    leg_a = _TrackedLeg(leg_id="a", chunks=[b"a-token"])
    leg_b = _TrackedLeg(leg_id="b", chunks=[b"b-token"])
    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    leg_anchor.to_race_leg(handicap_seconds=10.0),
                    leg_a.to_race_leg(handicap_seconds=0.0),
                    leg_b.to_race_leg(handicap_seconds=0.0),
                ],
            )
        )
        await asyncio.wait_for(leg_anchor.started.wait(), timeout=1.0)
        assert leg_a.started.is_set() is False
        assert leg_b.started.is_set() is False
        assert clock.now() == pytest.approx(1000.0)

        clock.advance(10.0)
        await asyncio.sleep(0)
        await asyncio.wait_for(leg_a.started.wait(), timeout=1.0)
        await asyncio.wait_for(leg_b.started.wait(), timeout=1.0)
        assert clock.now() == pytest.approx(1010.0)

        leg_a.release_first_token.set()
        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "a"
    assert output == [b"a-token"]
    assert leg_anchor.cancel_calls == 1
    assert leg_b.cancel_calls == 1


@pytest.mark.asyncio
async def test_parallel_racer_eliminates_leg_on_ttft_timeout() -> None:
    leg_slow = _TrackedLeg(leg_id="slow", chunks=[b"slow-token"])
    leg_timeout = _TrackedLeg(leg_id="timeout", chunks=[b"timeout-token"])
    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    leg_slow.to_race_leg(),
                    leg_timeout.to_race_leg(ttft_timeout_seconds=2.0),
                ],
            )
        )
        await asyncio.wait_for(leg_slow.started.wait(), timeout=1.0)
        await asyncio.wait_for(leg_timeout.started.wait(), timeout=1.0)

        clock.advance(2.0)
        await asyncio.sleep(0)
        assert leg_timeout.cancel_calls == 1

        leg_slow.release_first_token.set()
        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

        assert winner == "slow"
        assert output == [b"slow-token"]


@pytest.mark.asyncio
async def test_parallel_racer_emits_keepalives_until_first_token() -> None:
    leg_a = _TrackedLeg(leg_id="a", chunks=[b"a-token"])
    leg_b = _TrackedLeg(leg_id="b", chunks=[b"b-token"])
    racer = ParallelCompletionRacer()
    keepalives: list[bytes] = []

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [leg_a.to_race_leg(), leg_b.to_race_leg()],
                keepalive_factory=lambda: b": keepalive\n\n",
            )
        )
        await asyncio.wait_for(leg_a.started.wait(), timeout=1.0)
        await asyncio.wait_for(leg_b.started.wait(), timeout=1.0)

        clock.advance(5.0)
        await asyncio.sleep(0)
        clock.advance(5.0)
        await asyncio.sleep(0)

        leg_a.release_first_token.set()
        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    keepalives = [chunk for chunk in output if chunk == b": keepalive\n\n"]
    assert winner == "a"
    assert len(keepalives) == 2
    assert output[-1] == b"a-token"


@pytest.mark.asyncio
async def test_parallel_racer_stops_all_legs_when_a_leg_cancelled() -> None:
    leg_a = _TrackedLeg(leg_id="a", chunks=[b"a-token", b"a-rest"])
    leg_b = _TrackedLeg(leg_id="b", chunks=[b"b-token", b"b-rest"])
    client_cancelled = asyncio.Event()
    racer = ParallelCompletionRacer()

    race_task = asyncio.create_task(
        _collect_race_output(
            racer,
            [leg_a.to_race_leg(), leg_b.to_race_leg()],
            client_cancelled=client_cancelled,
        )
    )
    await asyncio.wait_for(leg_a.started.wait(), timeout=1.0)
    await asyncio.wait_for(leg_b.started.wait(), timeout=1.0)

    client_cancelled.set()
    output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner is None
    assert output == []
    assert leg_a.cancel_calls == 1
    assert leg_b.cancel_calls == 1


@pytest.mark.asyncio
async def test_parallel_racer_invokes_protocol_cancel_before_closing_loser_streams() -> (
    None
):
    cancel_order: list[str] = []

    async def _cancel_a() -> None:
        cancel_order.append("a-cancel-start")
        await asyncio.sleep(0)
        cancel_order.append("a-cancel-done")

    async def _stream_a() -> AsyncIterator[bytes]:
        yield b"a-token"
        cancel_order.append("a-stream-after-token")

    async def _cancel_b() -> None:
        cancel_order.append("b-cancel-start")
        await asyncio.sleep(0)
        cancel_order.append("b-cancel-done")

    async def _stream_b() -> AsyncIterator[bytes]:
        await asyncio.sleep(0.05)
        yield b"b-token"

    racer = ParallelCompletionRacer()
    output, winner = await _collect_race_output(
        racer,
        [
            ParallelRaceLeg(
                leg_id="a",
                stream_factory=_stream_a,
                cancel=_cancel_a,
            ),
            ParallelRaceLeg(
                leg_id="b",
                stream_factory=_stream_b,
                cancel=_cancel_b,
            ),
        ],
    )

    assert winner == "a"
    assert output == [b"a-token"]
    assert cancel_order.index("b-cancel-start") < cancel_order.index("b-cancel-done")
    assert "a-cancel-start" not in cancel_order


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chunk", "expected_winner"),
    [
        (b"", "b"),
        (b"   \n", "b"),
        (b": keep-alive\n\n", "b"),
        (b": keepalive\n\n", "b"),
        ("", "b"),
        ("  \t", "b"),
        (": keep-alive\n\n", "b"),
        (": keepalive\n\n", "b"),
        ({"_keepalive": True}, "b"),
        (
            {"choices": [{"delta": {"content": "hello"}}]},
            "a",
        ),
        (
            {"choices": [{"delta": {"reasoning_content": "think"}}]},
            "a",
        ),
        (
            {"choices": [{"delta": {"reasoning": "think"}}]},
            "a",
        ),
        (
            {"choices": [{"delta": {"thinking": "think"}}]},
            "a",
        ),
        (
            {"choices": [{"delta": {"thought": "think"}}]},
            "a",
        ),
        (
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "lookup"},
                                }
                            ]
                        }
                    }
                ]
            },
            "a",
        ),
        (
            {"choices": [{"delta": {"content": "  "}}]},
            "b",
        ),
        ({"choices": [{"delta": {}}]}, "b"),
        (
            b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
            "b",
        ),
        (
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
            "b",
        ),
        (
            b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n',
            "a",
        ),
        (
            'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n',
            "a",
        ),
        (
            'data: {"choices":[{"delta":{"reasoning":"think"}}]}\n\n',
            "a",
        ),
        (
            'data: {"choices":[{"delta":{"thinking":"think"}}]}\n\n',
            "a",
        ),
        (
            'data: {"choices":[{"delta":{"thought":"think"}}]}\n\n',
            "a",
        ),
        (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","type":"function","function":{"name":"fn"}}]}}]}\n\n',
            "a",
        ),
        (b"data: [DONE]\n\n", "b"),
        ("data: [DONE]\n\n", "b"),
    ],
)
async def test_parallel_racer_ignores_non_meaningful_first_tokens(
    chunk: bytes | str | dict[str, object],
    expected_winner: str,
) -> None:
    async def _stream_a() -> AsyncIterator[bytes | str | dict[str, object]]:
        yield chunk
        if expected_winner == "a":
            return
        await asyncio.Event().wait()

    async def _stream_b() -> AsyncIterator[bytes]:
        yield b"b-token"

    async def _noop_cancel() -> None:
        return

    racer = ParallelCompletionRacer()
    output, winner = await _collect_race_output(
        racer,
        [
            ParallelRaceLeg(leg_id="a", stream_factory=_stream_a, cancel=_noop_cancel),
            ParallelRaceLeg(leg_id="b", stream_factory=_stream_b, cancel=_noop_cancel),
        ],
    )

    assert winner == expected_winner
    if expected_winner == "a":
        assert output[0] == chunk
    else:
        assert output == [b"b-token"]


@pytest.mark.asyncio
async def test_parallel_racer_aclose_cancels_active_and_pending_legs_callback_first() -> (
    None
):
    cancel_order: list[str] = []
    active_started = asyncio.Event()
    pending_started = asyncio.Event()

    async def _cancel_active() -> None:
        cancel_order.append("active-cancel-start")
        await asyncio.sleep(0)
        cancel_order.append("active-cancel-done")

    async def _stream_active() -> AsyncIterator[bytes]:
        active_started.set()
        yield b": keepalive\n\n"
        await asyncio.Event().wait()

    async def _cancel_pending() -> None:
        cancel_order.append("pending-cancel-start")
        await asyncio.sleep(0)
        cancel_order.append("pending-cancel-done")

    async def _stream_pending() -> AsyncIterator[bytes]:
        pending_started.set()
        yield b"pending-token"

    racer = ParallelCompletionRacer()

    async def _consume_until_cancelled() -> None:
        async for _chunk, _winner in racer.race(
            [
                ParallelRaceLeg(
                    leg_id="active",
                    stream_factory=_stream_active,
                    cancel=_cancel_active,
                    handicap_seconds=10.0,
                ),
                ParallelRaceLeg(
                    leg_id="pending",
                    stream_factory=_stream_pending,
                    cancel=_cancel_pending,
                    handicap_seconds=0.0,
                ),
            ]
        ):
            await asyncio.Event().wait()

    race_task = asyncio.create_task(_consume_until_cancelled())
    await asyncio.wait_for(active_started.wait(), timeout=1.0)
    assert pending_started.is_set() is False

    race_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await race_task
    await asyncio.sleep(0)

    assert "active-cancel-start" in cancel_order
    assert "pending-cancel-start" in cancel_order
    assert cancel_order.index("active-cancel-start") < cancel_order.index(
        "active-cancel-done"
    )
    assert cancel_order.index("pending-cancel-start") < cancel_order.index(
        "pending-cancel-done"
    )


@pytest.mark.asyncio
async def test_parallel_racer_processed_response_reasoning_wins_over_keepalive() -> (
    None
):
    async def _stream_a() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content=": keep-alive\n\n",
            metadata={"_keepalive": True},
        )
        yield ProcessedResponse(content="   ")
        yield ProcessedResponse(
            content={"choices": [{"delta": {"reasoning_content": "think"}}]},
        )

    async def _stream_b() -> AsyncIterator[ProcessedResponse]:
        await asyncio.sleep(0.05)
        yield ProcessedResponse(content={"choices": [{"delta": {"content": "lose"}}]})

    async def _noop_cancel() -> None:
        return

    racer = ParallelCompletionRacer()
    output, winner = await _collect_race_output(
        racer,
        [
            ParallelRaceLeg(leg_id="a", stream_factory=_stream_a, cancel=_noop_cancel),
            ParallelRaceLeg(leg_id="b", stream_factory=_stream_b, cancel=_noop_cancel),
        ],
    )

    assert winner == "a"
    assert isinstance(output[0], ProcessedResponse)
    assert output[0].content == {
        "choices": [{"delta": {"reasoning_content": "think"}}],
    }


@pytest.mark.asyncio
async def test_parallel_racer_handicapped_failure_accelerates_pending_legs() -> None:
    high_started = asyncio.Event()
    leg_low = _TrackedLeg(leg_id="low", chunks=[b"low-token"])
    racer = ParallelCompletionRacer()

    async def _stream_high() -> AsyncIterator[bytes]:
        high_started.set()
        if False:
            yield b""

    async def _noop_cancel_high() -> None:
        return

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    ParallelRaceLeg(
                        leg_id="high",
                        stream_factory=_stream_high,
                        cancel=_noop_cancel_high,
                        handicap_seconds=10.0,
                    ),
                    leg_low.to_race_leg(handicap_seconds=0.0),
                ],
            )
        )
        await asyncio.wait_for(high_started.wait(), timeout=1.0)
        assert leg_low.started.is_set() is False
        assert clock.now() == pytest.approx(1000.0)

        await asyncio.sleep(0)
        await asyncio.wait_for(leg_low.started.wait(), timeout=1.0)
        assert clock.now() == pytest.approx(1000.0)

        leg_low.release_first_token.set()
        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "low"
    assert output == [b"low-token"]


@pytest.mark.asyncio
async def test_parallel_racer_terminal_error_on_handicapped_leg_accelerates_pending() -> (
    None
):
    pending_started = asyncio.Event()

    async def _stream_high() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content={"error": {"message": "backend failed"}},
            metadata={"finish_reason": "error", "error": {"message": "backend failed"}},
        )

    async def _stream_low() -> AsyncIterator[bytes]:
        pending_started.set()
        yield b"low-token"

    async def _noop_cancel() -> None:
        return

    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    ParallelRaceLeg(
                        leg_id="high",
                        stream_factory=_stream_high,
                        cancel=_noop_cancel,
                        handicap_seconds=10.0,
                    ),
                    ParallelRaceLeg(
                        leg_id="low",
                        stream_factory=_stream_low,
                        cancel=_noop_cancel,
                        handicap_seconds=0.0,
                    ),
                ],
            )
        )
        await asyncio.sleep(0)
        await asyncio.wait_for(pending_started.wait(), timeout=1.0)
        assert clock.now() == pytest.approx(1000.0)

        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "low"
    assert output == [b"low-token"]


@pytest.mark.asyncio
async def test_parallel_racer_zero_handicap_failure_does_not_accelerate_schedule() -> (
    None
):
    leg_a = _TrackedLeg(leg_id="a", chunks=[])
    leg_b = _TrackedLeg(leg_id="b", chunks=[b"b-token"])
    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [leg_a.to_race_leg(), leg_b.to_race_leg()],
            )
        )
        await asyncio.wait_for(leg_a.started.wait(), timeout=1.0)
        await asyncio.wait_for(leg_b.started.wait(), timeout=1.0)
        assert clock.now() == pytest.approx(1000.0)

        leg_b.release_first_token.set()
        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "b"
    assert output == [b"b-token"]


@pytest.mark.asyncio
async def test_parallel_racer_client_cancel_after_winner_cancels_winner_and_blocks_pending() -> (
    None
):
    leg_winner = _TrackedLeg(leg_id="winner", chunks=[b"win-token", b"win-rest"])
    leg_winner.release_rest = asyncio.Event()
    leg_loser = _TrackedLeg(leg_id="loser", chunks=[b"lose-token"])
    leg_pending = _TrackedLeg(leg_id="pending", chunks=[b"pending-token"])
    client_cancelled = asyncio.Event()
    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    leg_winner.to_race_leg(handicap_seconds=10.0),
                    leg_loser.to_race_leg(handicap_seconds=10.0),
                    leg_pending.to_race_leg(handicap_seconds=0.0),
                ],
                client_cancelled=client_cancelled,
            )
        )
        await asyncio.wait_for(leg_winner.started.wait(), timeout=1.0)
        await asyncio.wait_for(leg_loser.started.wait(), timeout=1.0)
        assert leg_pending.started.is_set() is False

        leg_winner.release_first_token.set()
        await asyncio.sleep(0)
        client_cancelled.set()
        output, winner = await asyncio.wait_for(race_task, timeout=1.0)

        clock.advance(10.0)
        await asyncio.sleep(0)

    assert winner == "winner"
    assert output == [b"win-token"]
    assert leg_loser.cancel_calls == 1
    assert leg_winner.cancel_calls == 1
    assert leg_pending.cancel_calls == 1
    assert leg_pending.started.is_set() is False


@pytest.mark.asyncio
async def test_parallel_racer_retries_protocol_cancel_after_callback_failure() -> None:
    leg_winner = _TrackedLeg(leg_id="winner", chunks=[b"win-token", b"win-rest"])
    leg_winner.release_rest = asyncio.Event()
    leg_loser = _FlakyCancelLeg(leg_id="loser", chunks=[b"lose-token"])
    client_cancelled = asyncio.Event()
    racer = ParallelCompletionRacer()

    race_task = asyncio.create_task(
        _collect_race_output(
            racer,
            [leg_winner.to_race_leg(), leg_loser.to_race_leg()],
            client_cancelled=client_cancelled,
        )
    )
    await asyncio.wait_for(leg_winner.started.wait(), timeout=1.0)
    await asyncio.wait_for(leg_loser.started.wait(), timeout=1.0)

    leg_winner.release_first_token.set()
    await asyncio.sleep(0)
    client_cancelled.set()
    output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "winner"
    assert output == [b"win-token"]
    assert leg_loser.cancel_calls == 2


@pytest.mark.asyncio
async def test_parallel_racer_aclose_after_winner_cancels_winner_stream() -> None:
    leg_winner = _TrackedLeg(leg_id="winner", chunks=[b"win-token", b"win-rest"])
    leg_loser = _TrackedLeg(leg_id="loser", chunks=[b"lose-token"])
    racer = ParallelCompletionRacer()

    async def _consume_first_token_only() -> None:
        async for _chunk, _winner in racer.race(
            [leg_winner.to_race_leg(), leg_loser.to_race_leg()],
        ):
            return

    race_task = asyncio.create_task(_consume_first_token_only())
    await asyncio.wait_for(leg_winner.started.wait(), timeout=1.0)
    await asyncio.wait_for(leg_loser.started.wait(), timeout=1.0)

    leg_winner.release_first_token.set()
    await asyncio.wait_for(race_task, timeout=1.0)
    await asyncio.sleep(0)

    assert leg_loser.cancel_calls == 1
    assert leg_winner.cancel_calls == 1


@pytest.mark.asyncio
async def test_parallel_racer_does_not_leak_background_tasks() -> None:
    leg_a = _TrackedLeg(leg_id="a", chunks=[b"a-token"])
    leg_b = _TrackedLeg(leg_id="b", chunks=[b"b-token"])
    racer = ParallelCompletionRacer()

    before = {
        task for task in asyncio.all_tasks() if task is not asyncio.current_task()
    }
    race_task = asyncio.create_task(
        _collect_race_output(
            racer,
            [leg_a.to_race_leg(), leg_b.to_race_leg()],
        )
    )
    await asyncio.wait_for(leg_a.started.wait(), timeout=1.0)
    await asyncio.wait_for(leg_b.started.wait(), timeout=1.0)
    leg_a.release_first_token.set()
    output, winner = await asyncio.wait_for(race_task, timeout=1.0)
    await asyncio.sleep(0)
    after = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}

    assert winner == "a"
    assert output == [b"a-token"]
    leaked = after - before
    assert all(task.done() for task in leaked)


@pytest.mark.asyncio
async def test_parallel_racer_loser_cancel_requested_before_winner_chunk_consumed() -> (
    None
):
    loser_cancel_started = asyncio.Event()
    release_loser_cancel = asyncio.Event()
    winner_consumed = asyncio.Event()

    async def _noop_cancel_a() -> None:
        return

    async def _cancel_b() -> None:
        loser_cancel_started.set()
        await release_loser_cancel.wait()

    async def _stream_a() -> AsyncIterator[bytes]:
        yield b"a-token"
        await winner_consumed.wait()

    async def _stream_b() -> AsyncIterator[bytes]:
        await asyncio.Event().wait()
        yield b"never"

    racer = ParallelCompletionRacer()

    async def _consume_first_chunk() -> tuple[list[bytes], str | None]:
        output: list[bytes] = []
        winning_leg_id: str | None = None
        async for chunk, winner in racer.race(
            [
                ParallelRaceLeg(
                    leg_id="a",
                    stream_factory=_stream_a,
                    cancel=_noop_cancel_a,
                ),
                ParallelRaceLeg(
                    leg_id="b",
                    stream_factory=_stream_b,
                    cancel=_cancel_b,
                ),
            ],
        ):
            output.append(chunk)
            if winner is not None:
                winning_leg_id = winner
            winner_consumed.set()
            break
        return output, winning_leg_id

    race_task = asyncio.create_task(_consume_first_chunk())
    await asyncio.wait_for(loser_cancel_started.wait(), timeout=1.0)
    assert winner_consumed.is_set() is False

    release_loser_cancel.set()
    output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "a"
    assert output == [b"a-token"]
    assert winner_consumed.is_set() is True


@pytest.mark.asyncio
async def test_parallel_racer_routing_error_is_handled_as_unavailable_leg(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="src.core.services.parallel_completion_racer")
    failed_cancelled = asyncio.Event()
    fallback_started = asyncio.Event()

    async def _failed_stream() -> AsyncIterator[bytes]:
        raise RoutingError(
            message="No available backend instance for 'nvidia:deepseek-ai/deepseek-v4-pro'."
        )
        yield b"never"

    async def _fallback_stream() -> AsyncIterator[bytes]:
        fallback_started.set()
        yield b"fallback-token"

    async def _failed_cancel() -> None:
        failed_cancelled.set()

    async def _noop_cancel() -> None:
        return

    racer = ParallelCompletionRacer()
    output: list[bytes] = []
    winner_id: str | None = None
    async for chunk, winner in racer.race(
        [
            ParallelRaceLeg(
                leg_id="parallel-1-openai:gpt-4",
                stream_factory=_fallback_stream,
                cancel=_noop_cancel,
                model="openai:gpt-4",
            ),
            ParallelRaceLeg(
                leg_id="parallel-0-nvidia:deepseek-ai/deepseek-v4-pro?reasoning_effort=max",
                stream_factory=_failed_stream,
                cancel=_failed_cancel,
                handicap_seconds=10.0,
                model="nvidia:deepseek-ai/deepseek-v4-pro?reasoning_effort=max",
            ),
        ]
    ):
        output.append(chunk)
        if winner is not None:
            winner_id = winner

    assert output == [b"fallback-token"]
    assert winner_id == "parallel-1-openai:gpt-4"
    assert failed_cancelled.is_set()
    assert fallback_started.is_set()
    assert "Parallel race leg became unavailable before winning" in caplog.text
    assert "Parallel race leg failed before winning" not in caplog.text


@pytest.mark.asyncio
async def test_parallel_racer_cancels_losers_concurrently() -> None:
    cancel_started: dict[str, asyncio.Event] = {
        leg_id: asyncio.Event() for leg_id in ("b", "c", "d")
    }
    cancel_release: dict[str, asyncio.Event] = {
        leg_id: asyncio.Event() for leg_id in ("b", "c", "d")
    }
    cancel_order: list[str] = []

    def _make_cancel(leg_id: str) -> Callable[[], Awaitable[None]]:
        async def _cancel() -> None:
            cancel_order.append(f"{leg_id}-cancel-start")
            cancel_started[leg_id].set()
            await cancel_release[leg_id].wait()
            cancel_order.append(f"{leg_id}-cancel-done")

        return _cancel

    async def _stream_winner() -> AsyncIterator[bytes]:
        yield b"win-token"

    async def _stream_loser() -> AsyncIterator[bytes]:
        await asyncio.Event().wait()
        yield b"never"

    async def _noop_cancel() -> None:
        return

    racer = ParallelCompletionRacer()
    race_task = asyncio.create_task(
        _collect_race_output(
            racer,
            [
                ParallelRaceLeg(
                    leg_id="a",
                    stream_factory=_stream_winner,
                    cancel=_noop_cancel,
                ),
                ParallelRaceLeg(
                    leg_id="b",
                    stream_factory=_stream_loser,
                    cancel=_make_cancel("b"),
                ),
                ParallelRaceLeg(
                    leg_id="c",
                    stream_factory=_stream_loser,
                    cancel=_make_cancel("c"),
                ),
                ParallelRaceLeg(
                    leg_id="d",
                    stream_factory=_stream_loser,
                    cancel=_make_cancel("d"),
                ),
            ],
        )
    )
    await asyncio.wait_for(
        asyncio.gather(
            *(cancel_started[leg_id].wait() for leg_id in ("b", "c", "d")),
        ),
        timeout=1.0,
    )
    for leg_id in ("b", "c", "d"):
        cancel_release[leg_id].set()
    output, winner = await asyncio.wait_for(race_task, timeout=1.0)

    assert winner == "a"
    assert output == [b"win-token"]
    start_indices = [
        cancel_order.index(f"{leg_id}-cancel-start") for leg_id in ("b", "c", "d")
    ]
    done_indices = [
        cancel_order.index(f"{leg_id}-cancel-done") for leg_id in ("b", "c", "d")
    ]
    assert max(start_indices) < min(done_indices)


@pytest.mark.asyncio
async def test_parallel_racer_terminal_error_leg_self_cancels() -> None:
    self_cancel_calls = 0

    async def _cancel_high() -> None:
        nonlocal self_cancel_calls
        self_cancel_calls += 1

    async def _stream_high() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content={"error": {"message": "backend failed"}},
            metadata={"finish_reason": "error", "error": {"message": "backend failed"}},
        )

    async def _stream_low() -> AsyncIterator[bytes]:
        yield b"low-token"

    async def _noop_cancel_low() -> None:
        return

    racer = ParallelCompletionRacer()
    output, winner = await _collect_race_output(
        racer,
        [
            ParallelRaceLeg(
                leg_id="high",
                stream_factory=_stream_high,
                cancel=_cancel_high,
                handicap_seconds=0.0,
            ),
            ParallelRaceLeg(
                leg_id="low",
                stream_factory=_stream_low,
                cancel=_noop_cancel_low,
                handicap_seconds=0.0,
            ),
        ],
    )

    assert winner == "low"
    assert output == [b"low-token"]
    assert self_cancel_calls == 1


@pytest.mark.asyncio
async def test_parallel_racer_exception_leg_self_cancels() -> None:
    self_cancel_calls = 0

    async def _cancel_failing() -> None:
        nonlocal self_cancel_calls
        self_cancel_calls += 1

    async def _stream_failing() -> AsyncIterator[bytes]:
        raise RuntimeError("stream exploded")
        yield b""  # pragma: no cover

    async def _stream_winner() -> AsyncIterator[bytes]:
        await asyncio.sleep(0.05)
        yield b"win-token"

    async def _noop_cancel_winner() -> None:
        return

    racer = ParallelCompletionRacer()
    output, winner = await _collect_race_output(
        racer,
        [
            ParallelRaceLeg(
                leg_id="failing",
                stream_factory=_stream_failing,
                cancel=_cancel_failing,
            ),
            ParallelRaceLeg(
                leg_id="winner",
                stream_factory=_stream_winner,
                cancel=_noop_cancel_winner,
            ),
        ],
    )

    assert winner == "winner"
    assert output == [b"win-token"]
    assert self_cancel_calls == 1


@pytest.mark.asyncio
async def test_parallel_racer_skipped_pending_leg_logs_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    leg_high = _TrackedLeg(leg_id="high", chunks=[b"high-token"])
    leg_low = _TrackedLeg(leg_id="low", chunks=[b"low-token"])
    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    leg_high.to_race_leg(handicap_seconds=10.0),
                    leg_low.to_race_leg(handicap_seconds=0.0),
                ],
            )
        )
        await asyncio.wait_for(leg_high.started.wait(), timeout=1.0)
        leg_high.release_first_token.set()
        await asyncio.wait_for(race_task, timeout=1.0)

        clock.advance(10.0)
        await asyncio.sleep(0)

    not_started_records = [
        record
        for record in caplog.records
        if record.levelno == logging.INFO
        and "parallel_race_leg_not_started" in record.getMessage()
    ]
    assert not_started_records
    assert any(
        "reason=winner_already_selected" in record.getMessage()
        for record in not_started_records
    )
    assert any("leg=low" in record.getMessage() for record in not_started_records)


@pytest.mark.asyncio
async def test_parallel_racer_cancel_logging_uses_neutral_event_names(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    leg_a = _TrackedLeg(leg_id="a", chunks=[b"a-token"])
    leg_b = _TrackedLeg(leg_id="b", chunks=[b"b-token"])
    racer = ParallelCompletionRacer()

    race_task = asyncio.create_task(
        _collect_race_output(
            racer,
            [leg_a.to_race_leg(), leg_b.to_race_leg()],
        )
    )
    await asyncio.wait_for(leg_a.started.wait(), timeout=1.0)
    await asyncio.wait_for(leg_b.started.wait(), timeout=1.0)
    leg_a.release_first_token.set()
    await asyncio.wait_for(race_task, timeout=1.0)

    messages = [record.getMessage() for record in caplog.records]
    assert any("parallel_race_leg_cancel_requested" in msg for msg in messages)
    assert any("parallel_race_leg_cancel_callback_completed" in msg for msg in messages)
    assert not any("parallel_race_loser" in msg for msg in messages)
    cancel_requested = next(
        msg for msg in messages if "parallel_race_leg_cancel_requested" in msg
    )
    assert "reason=" in cancel_requested
    assert "leg=" in cancel_requested
    assert "winner=" in cancel_requested
    assert "started=True" in cancel_requested


@pytest.mark.asyncio
async def test_parallel_racer_cancel_requested_started_false_for_pending_leg(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    leg_high = _TrackedLeg(leg_id="high", chunks=[b"high-token"])
    leg_low = _TrackedLeg(leg_id="low", chunks=[b"low-token"])
    racer = ParallelCompletionRacer()

    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        race_task = asyncio.create_task(
            _collect_race_output(
                racer,
                [
                    leg_high.to_race_leg(handicap_seconds=10.0),
                    leg_low.to_race_leg(handicap_seconds=0.0),
                ],
            )
        )
        await asyncio.wait_for(leg_high.started.wait(), timeout=1.0)
        leg_high.release_first_token.set()
        await asyncio.wait_for(race_task, timeout=1.0)

        clock.advance(10.0)
        await asyncio.sleep(0)

    cancel_records = [
        record.getMessage()
        for record in caplog.records
        if "parallel_race_leg_cancel_requested" in record.getMessage()
        and "leg=low" in record.getMessage()
    ]
    assert cancel_records
    assert all("started=False" in message for message in cancel_records)


@pytest.mark.asyncio
async def test_parallel_racer_logs_cancel_callback_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    async def _failing_cancel() -> None:
        raise RuntimeError("cancel boom")

    async def _stream_a() -> AsyncIterator[bytes]:
        yield b"a-token"

    async def _stream_b() -> AsyncIterator[bytes]:
        await asyncio.Event().wait()
        yield b"never"

    async def _noop_cancel() -> None:
        return

    racer = ParallelCompletionRacer()
    output, winner = await _collect_race_output(
        racer,
        [
            ParallelRaceLeg(
                leg_id="a",
                stream_factory=_stream_a,
                cancel=_noop_cancel,
            ),
            ParallelRaceLeg(
                leg_id="b",
                stream_factory=_stream_b,
                cancel=_failing_cancel,
                model="test-model",
            ),
        ],
    )

    assert winner == "a"
    assert output == [b"a-token"]
    failed_records = [
        record
        for record in caplog.records
        if "parallel_race_leg_cancel_callback_failed" in record.getMessage()
    ]
    assert failed_records
    message = failed_records[0].getMessage()
    assert "reason=winner_selected" in message
    assert "leg=b" in message
    assert "model=test-model" in message
    assert "winner=a" in message


@pytest.mark.asyncio
async def test_parallel_racer_aclose_mid_claim_waits_for_first_chunk() -> None:
    loser_cancel_started = asyncio.Event()
    release_loser_cancel = asyncio.Event()
    winner_cancel_started = asyncio.Event()

    async def _cancel_b() -> None:
        loser_cancel_started.set()
        await release_loser_cancel.wait()

    async def _cancel_a() -> None:
        winner_cancel_started.set()

    async def _stream_a() -> AsyncIterator[bytes]:
        yield b"win-token"
        await asyncio.Event().wait()

    async def _stream_b() -> AsyncIterator[bytes]:
        await asyncio.Event().wait()
        yield b"never"

    racer = ParallelCompletionRacer()

    async def _consume() -> None:
        async for _chunk, _winner in racer.race(
            [
                ParallelRaceLeg(
                    leg_id="a",
                    stream_factory=_stream_a,
                    cancel=_cancel_a,
                ),
                ParallelRaceLeg(
                    leg_id="b",
                    stream_factory=_stream_b,
                    cancel=_cancel_b,
                ),
            ]
        ):
            await asyncio.Event().wait()

    race_task = asyncio.create_task(_consume())
    await asyncio.wait_for(loser_cancel_started.wait(), timeout=1.0)
    assert winner_cancel_started.is_set() is False

    race_task.cancel()
    release_loser_cancel.set()
    with pytest.raises(asyncio.CancelledError):
        await race_task
    await asyncio.wait_for(winner_cancel_started.wait(), timeout=1.0)
    await asyncio.sleep(0)
    leaked = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert not leaked


@pytest.mark.asyncio
async def test_parallel_racer_aclose_aborted_race_cleans_up_background_tasks() -> None:
    active_started = asyncio.Event()

    async def _noop_cancel() -> None:
        return

    async def _stream_active() -> AsyncIterator[bytes]:
        active_started.set()
        yield b": keepalive\n\n"
        await asyncio.Event().wait()

    racer = ParallelCompletionRacer()

    async def _consume_until_cancelled() -> None:
        async for _chunk, _winner in racer.race(
            [
                ParallelRaceLeg(
                    leg_id="active",
                    stream_factory=_stream_active,
                    cancel=_noop_cancel,
                    handicap_seconds=10.0,
                ),
            ]
        ):
            await asyncio.Event().wait()

    race_task = asyncio.create_task(_consume_until_cancelled())
    await asyncio.wait_for(active_started.wait(), timeout=1.0)

    race_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await race_task
    await asyncio.sleep(0)

    leaked = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert not leaked
