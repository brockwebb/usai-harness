"""Tests for the `batch()` progress callback (ADR-017 / FR-066) and the
built-in `text_progress` formatter (ADR-017 amendment 2026-05-06 / 0.8.1)."""

import asyncio
import logging
import re
import time

import pytest

from usai_harness import ProgressEvent, text_progress
from usai_harness.client import USAiClient
from usai_harness.progress import _fmt_time
from usai_harness.transport import BaseTransport
from usai_harness.worker_pool import AuthHaltError


def _ok_response(model: str = "claude-sonnet-4-5-20241022") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        "model": model,
    }


class _OKTransport(BaseTransport):
    def __init__(self):
        self.calls: list[dict] = []
        self.closed = False

    async def send(self, base_url, api_key, model, messages, **kw):
        self.calls.append({"model": model})
        return _ok_response(model), 200

    async def close(self):
        self.closed = True


class _FlakyTransport(BaseTransport):
    """Returns 500 on tasks named in `fail_ids` (max_retries exhausts), 200 otherwise."""

    def __init__(self, fail_payload_substrings: list[str]):
        self.fail_payload_substrings = fail_payload_substrings
        self.calls: list[dict] = []
        self.closed = False

    async def send(self, base_url, api_key, model, messages, **kw):
        self.calls.append({"messages": messages, "model": model})
        content = messages[0].get("content", "") if messages else ""
        if any(sub in content for sub in self.fail_payload_substrings):
            return ({}, 500)
        return _ok_response(model), 200

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path_factory):
    for var in ("USAI_API_KEY", "USAI_BASE_URL", "OPENROUTER_API_KEY",
                "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(var, raising=False)
    empty = tmp_path_factory.mktemp("empty_user_config")
    monkeypatch.setattr(
        "usai_harness.key_manager.user_config_env_path",
        lambda: empty / "usai-harness" / ".env",
    )


@pytest.fixture
def env_path(tmp_path):
    p = tmp_path / ".env"
    p.write_text("USAI_API_KEY=test-key-AAAAAAAA\n")
    return p


def _client(tmp_path, env_path, transport):
    return USAiClient(
        project="progress-test",
        env_path=env_path,
        transport=transport,
        log_dir=tmp_path / "logs",
        ledger_path=tmp_path / "ledger.jsonl",
    )


def _tasks(n: int) -> list[dict]:
    return [
        {"task_id": f"t{i:04d}", "messages": [{"role": "user", "content": f"q{i}"}]}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_callback_fires_exactly_n_times(tmp_path, env_path, capsys):
    events: list[ProgressEvent] = []
    client = _client(tmp_path, env_path, _OKTransport())
    try:
        results = await client.batch(
            _tasks(5), job_name="test-batch",
            progress=events.append,
        )
    finally:
        await client.close()
    capsys.readouterr()

    assert len(results) == 5
    assert len(events) == 5


@pytest.mark.asyncio
async def test_counters_are_monotonic(tmp_path, env_path, capsys):
    events: list[ProgressEvent] = []
    client = _client(tmp_path, env_path, _OKTransport())
    try:
        await client.batch(_tasks(7), progress=events.append)
    finally:
        await client.close()
    capsys.readouterr()

    # `completed` strictly increases by 1 per event.
    completed_values = [e.completed for e in events]
    assert completed_values == list(range(1, len(events) + 1))
    # `succeeded + failed == completed` invariant on every event.
    for e in events:
        assert e.succeeded + e.failed == e.completed
    # `succeeded` and `failed` are non-decreasing.
    assert all(
        events[i].succeeded <= events[i + 1].succeeded
        for i in range(len(events) - 1)
    )
    assert all(
        events[i].failed <= events[i + 1].failed
        for i in range(len(events) - 1)
    )


@pytest.mark.asyncio
async def test_final_event_has_completed_equals_total(tmp_path, env_path, capsys):
    events: list[ProgressEvent] = []
    client = _client(tmp_path, env_path, _OKTransport())
    try:
        await client.batch(_tasks(4), job_name="finals", progress=events.append)
    finally:
        await client.close()
    capsys.readouterr()

    assert events[-1].completed == events[-1].total == 4
    assert all(e.total == 4 for e in events)
    assert all(e.job_name == "finals" for e in events)


@pytest.mark.asyncio
async def test_succeeded_failed_partition_under_failures(tmp_path, env_path, capsys):
    events: list[ProgressEvent] = []
    transport = _FlakyTransport(fail_payload_substrings=["q1", "q3"])
    client = _client(tmp_path, env_path, transport)
    try:
        await client.batch(_tasks(5), progress=events.append)
    finally:
        await client.close()
    capsys.readouterr()

    final = events[-1]
    assert final.completed == 5
    assert final.succeeded == 3
    assert final.failed == 2


@pytest.mark.asyncio
async def test_callback_exception_does_not_affect_results(
    tmp_path, env_path, caplog, capsys,
):
    """A buggy callback must not poison the workload."""
    invocations = 0

    def buggy(_event):
        nonlocal invocations
        invocations += 1
        raise RuntimeError("oops")

    client = _client(tmp_path, env_path, _OKTransport())
    caplog.set_level(logging.WARNING, logger="usai_harness.progress")
    try:
        results = await client.batch(_tasks(3), progress=buggy)
    finally:
        await client.close()
    capsys.readouterr()

    assert len(results) == 3
    assert all(r.success for r in results)
    assert invocations == 3
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "progress callback raised" in r.getMessage()
        and "RuntimeError" in r.getMessage()
        for r in warnings
    )


@pytest.mark.asyncio
async def test_slow_callback_completes_workload(tmp_path, env_path, capsys):
    """A callback that does bounded synchronous work must not deadlock or
    drop events. Throughput will be slower (the callback runs inline on
    the event loop) but the workload completes."""
    events: list[ProgressEvent] = []

    def slow(event):
        # 50 ms of synchronous work per event; 10 events = ~0.5 s minimum.
        end = time.monotonic() + 0.05
        while time.monotonic() < end:
            pass
        events.append(event)

    client = _client(tmp_path, env_path, _OKTransport())
    try:
        results = await client.batch(_tasks(10), progress=slow)
    finally:
        await client.close()
    capsys.readouterr()

    assert len(results) == 10
    assert len(events) == 10
    assert events[-1].completed == 10


@pytest.mark.asyncio
async def test_progress_none_silences_output(tmp_path, env_path, capsys):
    """`progress=None` produces no stdout from the harness's default text
    formatter. Result list is unaffected."""
    client = _client(tmp_path, env_path, _OKTransport())
    try:
        results = await client.batch(_tasks(3), job_name="silent", progress=None)
    finally:
        await client.close()

    captured = capsys.readouterr().out
    # No status lines from text_progress.
    assert "silent" not in captured
    assert "elapsed" not in captured
    assert len(results) == 3


@pytest.mark.asyncio
async def test_progress_default_is_text_progress(tmp_path, env_path, capsys):
    """Default `batch()` (no progress kwarg) uses `text_progress` per
    ADR-017 amendment (0.8.1). Status lines appear on stdout."""
    client = _client(tmp_path, env_path, _OKTransport())
    try:
        results = await client.batch(_tasks(3), job_name="visible")
    finally:
        await client.close()

    out = capsys.readouterr().out
    assert "[visible]" in out
    assert "1/3" in out and "2/3" in out and "3/3" in out
    assert "elapsed" in out and "eta" in out
    assert len(results) == 3


@pytest.mark.asyncio
async def test_event_fields_populated(tmp_path, env_path, capsys):
    events: list[ProgressEvent] = []
    client = _client(tmp_path, env_path, _OKTransport())
    try:
        await client.batch(_tasks(2), job_name="fields", progress=events.append)
    finally:
        await client.close()
    capsys.readouterr()

    e = events[0]
    assert e.job_name == "fields"
    assert e.task_id.startswith("t")
    assert e.success is True
    assert e.status_code == 200
    assert e.latency_ms >= 0.0
    assert e.elapsed_seconds >= 0.0
    # Frozen dataclass.
    with pytest.raises(Exception):
        e.completed = 999  # type: ignore[misc]


# ---------- recovery interaction (FR-064 + ADR-017) -----------------------


class _AuthFlipBatchTransport(BaseTransport):
    """Returns 401 on the Nth call, then 200 forever (one-shot 401)."""

    def __init__(self, fail_after: int):
        self.fail_after = fail_after
        self._count = 0
        self._failed_once = False
        self.calls: list[dict] = []
        self.closed = False

    async def send(self, base_url, api_key, model, messages, **kw):
        self._count += 1
        self.calls.append({"api_key": api_key})
        if self._count == self.fail_after and not self._failed_once:
            self._failed_once = True
            return ({}, 401)
        return _ok_response(model), 200

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_recovery_emits_one_event_per_task_not_per_retry(
    tmp_path, env_path, monkeypatch, capsys,
):
    """Per ADR-017, a task that gets retried after credential recovery
    fires exactly one progress event when it ultimately reaches a
    terminal state — not one per retry. The total event count equals
    `total`, with the per-batch counters reflecting the original
    submission size."""
    events: list[ProgressEvent] = []
    monkeypatch.setattr(
        "usai_harness.client.recover_stale_credential",
        lambda **kw: "rotated-key",
    )
    transport = _AuthFlipBatchTransport(fail_after=2)
    client = _client(tmp_path, env_path, transport)
    try:
        results = await client.batch(_tasks(5), progress=events.append)
    finally:
        await client.close()
    capsys.readouterr()

    assert len(results) == 5
    assert len(events) == 5  # exactly total, not 5 + 1 retry.
    assert events[-1].completed == 5
    assert events[-1].total == 5
    # Counters monotonic across the recovery boundary.
    assert [e.completed for e in events] == [1, 2, 3, 4, 5]


# ---------- text_progress (ADR-017 amendment 2026-05-06 / 0.8.1) ----------


def _event(
    *,
    completed: int = 1,
    total: int = 5,
    succeeded: int = 1,
    failed: int = 0,
    success: bool = True,
    job_name: str = "stage1",
    task_id: str = "t0001",
    elapsed_seconds: float = 3.0,
) -> ProgressEvent:
    return ProgressEvent(
        job_name=job_name,
        task_id=task_id,
        completed=completed,
        total=total,
        succeeded=succeeded,
        failed=failed,
        success=success,
        status_code=200 if success else 500,
        latency_ms=120.0,
        elapsed_seconds=elapsed_seconds,
    )


def test_fmt_time_seconds():
    assert _fmt_time(0) == "0s"
    assert _fmt_time(7.4) == "7s"
    assert _fmt_time(59) == "59s"


def test_fmt_time_minutes():
    assert _fmt_time(60) == "1m 00s"
    assert _fmt_time(125) == "2m 05s"
    assert _fmt_time(3599) == "59m 59s"


def test_fmt_time_hours():
    assert _fmt_time(3600) == "1h 00m 00s"
    assert _fmt_time(3725) == "1h 02m 05s"


def test_fmt_time_negative_clamps_to_zero():
    assert _fmt_time(-1.0) == "0s"


def test_text_progress_writes_status_line(capsys):
    text_progress(_event(completed=3, total=10, succeeded=3, elapsed_seconds=9.0))
    out = capsys.readouterr().out
    # Timestamp prefix matches HH:MM:SS.
    assert re.match(r"\[\d{2}:\d{2}:\d{2}\] ", out)
    assert "[stage1]" in out
    assert "3/10" in out
    assert "(30.0%)" in out
    assert "elapsed 9s" in out
    # eta = 9 / 3 * 7 = 21s.
    assert "eta 21s" in out


def test_text_progress_omits_label_when_job_name_empty(capsys):
    text_progress(_event(job_name=""))
    out = capsys.readouterr().out
    # No "[<label>]" between the timestamp bracket and the count.
    # The line opens with `[HH:MM:SS] 1/5` rather than `[HH:MM:SS] [..] 1/5`.
    assert re.search(r"\] 1/5 ", out)


def test_text_progress_appends_fail_on_failure(capsys):
    text_progress(
        _event(success=False, task_id="stage1_rater_a_b0042", failed=1, succeeded=0),
    )
    out = capsys.readouterr().out
    assert "FAIL: stage1_rater_a_b0042" in out


def test_text_progress_zero_total_does_not_divide_by_zero(capsys):
    """Defensive: guards against an empty-batch edge case at the formatter."""
    text_progress(_event(completed=0, total=0, succeeded=0, elapsed_seconds=0.0))
    out = capsys.readouterr().out
    assert "0/0" in out
    assert "(0.0%)" in out


# ---------- ProgressEvent.result (ADR-017 amendment 2026-05-06 / 0.9.0) ----


@pytest.mark.asyncio
async def test_event_result_is_populated_with_batch_result(
    tmp_path, env_path, capsys,
):
    """Every fired ProgressEvent carries the completed task's full
    BatchResult — not just counters."""
    from usai_harness import BatchResult

    events: list[ProgressEvent] = []
    client = _client(tmp_path, env_path, _OKTransport())
    try:
        await client.batch(_tasks(3), progress=events.append)
    finally:
        await client.close()
    capsys.readouterr()

    assert len(events) == 3
    for e in events:
        assert e.result is not None
        assert isinstance(e.result, BatchResult)


@pytest.mark.asyncio
async def test_event_result_task_id_matches_event_task_id(
    tmp_path, env_path, capsys,
):
    """The task identifier on the event matches the identifier on the
    embedded result. Callers can rely on either field."""
    events: list[ProgressEvent] = []
    client = _client(tmp_path, env_path, _OKTransport())
    try:
        await client.batch(_tasks(4), progress=events.append)
    finally:
        await client.close()
    capsys.readouterr()

    for e in events:
        assert e.result.task_id == e.task_id


@pytest.mark.asyncio
async def test_event_result_response_carries_full_dict(
    tmp_path, env_path, capsys,
):
    """The result's `response` field carries the full provider response
    dict — caller can extract content, usage, model, etc. from the
    callback without waiting for batch() to return."""
    extracted: list[str] = []

    def collect_content(event):
        if event.result and event.result.response:
            choices = event.result.response.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                extracted.append(content)

    client = _client(tmp_path, env_path, _OKTransport())
    try:
        await client.batch(_tasks(3), progress=collect_content)
    finally:
        await client.close()
    capsys.readouterr()

    assert extracted == ["ok", "ok", "ok"]


@pytest.mark.asyncio
async def test_event_result_carries_failure_details(tmp_path, env_path, capsys):
    """For failed tasks, the embedded result preserves status_code and
    error so callers can route per-task error handling from the callback."""
    events: list[ProgressEvent] = []
    transport = _FlakyTransport(fail_payload_substrings=["q1"])
    client = _client(tmp_path, env_path, transport)
    try:
        await client.batch(_tasks(3), progress=events.append)
    finally:
        await client.close()
    capsys.readouterr()

    by_id = {e.task_id: e for e in events}
    failed_event = by_id["t0001"]
    assert failed_event.success is False
    assert failed_event.result is not None
    assert failed_event.result.success is False
    assert failed_event.result.status_code == 500
    assert failed_event.result.error is not None


@pytest.mark.asyncio
async def test_text_progress_unchanged_by_result_field(
    tmp_path, env_path, capsys,
):
    """text_progress does not reference event.result; output format is
    identical to 0.8.1."""
    client = _client(tmp_path, env_path, _OKTransport())
    try:
        await client.batch(_tasks(2), job_name="unchanged")
    finally:
        await client.close()
    out = capsys.readouterr().out
    # The standard 0.8.1 line shape: timestamp, label, count, percent, eta.
    assert "[unchanged]" in out
    assert "1/2" in out and "2/2" in out
    assert "elapsed" in out and "eta" in out
    # No embedded result/response payload leakage.
    assert "BatchResult" not in out
    assert "choices" not in out
