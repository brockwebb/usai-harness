"""Tests for the `batch()` progress callback (ADR-017 / FR-066)."""

import asyncio
import logging
import time

import pytest

from usai_harness import ProgressEvent
from usai_harness.client import USAiClient
from usai_harness.transport import BaseTransport
from usai_harness.worker_pool import AuthHaltError

pytestmark = pytest.mark.asyncio


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


async def test_progress_none_is_byte_identical(tmp_path, env_path, capsys):
    """Default `progress=None` behavior is unchanged: same results, no callback."""
    client_a = _client(tmp_path, env_path, _OKTransport())
    try:
        results_a = await client_a.batch(_tasks(3), job_name="b")
    finally:
        await client_a.close()
    capsys.readouterr()

    client_b = _client(tmp_path, env_path, _OKTransport())
    try:
        results_b = await client_b.batch(_tasks(3), job_name="b", progress=None)
    finally:
        await client_b.close()
    capsys.readouterr()

    # Result lists have the same shape (task ids and success flags).
    assert [r.task_id for r in results_a] == [r.task_id for r in results_b]
    assert [r.success for r in results_a] == [r.success for r in results_b]


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
