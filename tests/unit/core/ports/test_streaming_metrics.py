from src.core.ports.streaming_metrics import StreamingMetrics


def test_streaming_metrics_records_time_to_first_chunk_once() -> None:
    metrics = StreamingMetrics()
    stream_id = "stream-1"

    metrics.start_stream(stream_id)
    elapsed = metrics.stop_timer(stream_id, "time_to_first_chunk")
    assert elapsed is not None
    metrics.set_stream_metadata(stream_id, "time_to_first_chunk_seconds", elapsed)

    later = metrics.stop_timer(stream_id, "time_to_first_chunk")
    assert later is None

    metadata = metrics.get_stream_metadata(stream_id)
    assert metadata["time_to_first_chunk_seconds"] == elapsed
